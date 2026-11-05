"""Content Credentials, read with the real library from files signed here by a throwaway certificate."""

from __future__ import annotations

import http.server
import io
import json
import logging
import sys
import threading
import time
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from backend.media import MediaConfig, analyze_media
from backend.media import content_credentials as module
from backend.media.content_credentials import (
    CONTENT_CHANGED,
    CREDENTIALS_FAILED,
    INVALID,
    NOT_CHECKED,
    NOT_ON_TRUST_LIST,
    ON_TRUST_LIST,
    REMOTE_REASON,
    RULES_FAILED,
    SIGNED,
    UNSIGNED,
    interpret,
    offline_settings,
    read_credentials,
)
from backend.media.eval.content_credentials import _box_range
from backend.media.eval.content_credentials import main as eval_main
from backend.media.eval.throwaway_signer import make_signer, sign_bytes
from backend.media.explain import _content_credentials, build_checks
from backend.media.models import Assessment, CheckStatus, MediaType
from backend.media.tests.helpers import FakeClassifier, patterned_image, write_video

CONFIG = MediaConfig()
PERSON = "Private Person Name"
PRIVATE_ASSERTION = {
    "label": "stds.schema-org.CreativeWork",
    "data": {"@context": "http://schema.org/", "@type": "CreativeWork", "author": [{"@type": "Person", "name": PERSON}]},
    "kind": "Json",
}
MANIFEST_ID = "urn:c2pa:test"


@pytest.fixture(scope="module")
def signer():
    pytest.importorskip("c2pa")
    pytest.importorskip("cryptography")
    return make_signer()


@pytest.fixture(scope="module")
def expired_file(signer):
    """A file signed while its certificate was valid, and read after it expired. The library won't sign otherwise."""
    short_lived = make_signer(valid_for_seconds=3)
    signed = sign_bytes(image_bytes(), "image/jpeg", short_lived, source_type="trainedAlgorithmicMedia")
    time.sleep(4.2)
    return signed


@pytest.fixture
def web_server():
    """A local server that records requests, so a fetch can be seen. Nothing leaves this machine."""
    hits: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/manifest.c2pa", hits
    server.shutdown()
    server.server_close()


def image_bytes(image_format="JPEG", seed=1, size=256):
    buffer = io.BytesIO()
    patterned_image(seed, size).save(buffer, format=image_format)
    return buffer.getvalue()


def write(tmp_path, payload, name="file.jpg"):
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def read_bytes(tmp_path, payload, config=CONFIG, name="file.jpg"):
    return read_credentials(write(tmp_path, payload, name), config)


def signed_jpeg(signer, **options):
    return sign_bytes(image_bytes(), "image/jpeg", signer, **options)


def report(state="Valid", failures=(), manifest=None):
    return {
        "active_manifest": MANIFEST_ID,
        "manifests": {MANIFEST_ID: manifest if manifest is not None else {}},
        "validation_state": state,
        "validation_results": {"activeManifest": {"failure": [{"code": code} for code in failures]}},
    }


def actions(*source_types, label="c2pa.actions.v2"):
    return {
        "assertions": [
            {
                "label": label,
                "data": {
                    "actions": [
                        {"action": "c2pa.created", "digitalSourceType": f"https://cv.iptc.org/newscodes/digitalsourcetype/{kind}"}
                        for kind in source_types
                    ]
                },
            }
        ]
    }


def credentials_check(result):
    return {check["check_id"]: check for check in build_checks(result, config=CONFIG)}["media.c2pa"]


def check_text(check):
    return " ".join([check["result"], check["reasoning"], *check["limitations"]])


def analyze_result_with(check):
    return _content_credentials(check)


# Signed, unsigned and invalid, on real signed files


def test_a_file_with_no_credentials_reads_as_unsigned(tmp_path):
    pytest.importorskip("c2pa")
    check = read_bytes(tmp_path, image_bytes())
    assert check.status is CheckStatus.COMPLETE
    assert check.state == UNSIGNED
    assert check.signer_trust is None


@pytest.mark.parametrize(("image_format", "mime"), [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_signed_images_read_as_signed(tmp_path, signer, image_format, mime):
    check = read_bytes(tmp_path, sign_bytes(image_bytes(image_format), mime, signer))
    assert check.state == SIGNED
    assert check.status is CheckStatus.COMPLETE
    assert check.signer_organisation == "Throwaway Test Org"
    assert check.claim_generator == "throwaway-test-tool"
    assert check.declared_sources == ["digitalCapture"]
    assert check.failure_codes == []


def test_the_file_name_makes_no_difference(tmp_path, signer):
    assert read_bytes(tmp_path, signed_jpeg(signer), name="misleading.png").state == SIGNED
    assert read_bytes(tmp_path, signed_jpeg(signer), name="no_extension").state == SIGNED


def test_changing_the_content_after_signing_reads_as_invalid(tmp_path, signer):
    signed = bytearray(signed_jpeg(signer, source_type="trainedAlgorithmicMedia"))
    signed[-50] ^= 0xFF
    check = read_bytes(tmp_path, bytes(signed))
    assert check.state == INVALID
    assert check.invalid_reason == CONTENT_CHANGED
    assert "assertion.dataHash.mismatch" in check.failure_codes


def test_invalid_credentials_say_nothing_from_the_manifest(tmp_path, signer):
    signed = bytearray(signed_jpeg(signer, source_type="trainedAlgorithmicMedia"))
    signed[-50] ^= 0xFF
    check = read_bytes(tmp_path, bytes(signed))
    assert check.signer_organisation is None
    assert check.claim_generator is None
    assert check.declared_sources == []
    assert check.signer_trust is None


def test_changing_a_manifest_assertion_reads_as_invalid(tmp_path, signer):
    signed = bytearray(signed_jpeg(signer, extra_assertions=[PRIVATE_ASSERTION]))
    position = signed.find(PERSON.encode())
    assert position > 0
    # One letter changes to another, so the manifest still parses and its hash is what fails.
    signed[position] ^= 0x01
    check = read_bytes(tmp_path, bytes(signed))
    assert check.state == INVALID
    assert check.invalid_reason == CREDENTIALS_FAILED
    assert "assertion.hashedURI.mismatch" in check.failure_codes


def test_breaking_the_manifest_structure_reads_as_invalid(tmp_path, signer):
    """The library raises an error for this one rather than reporting a state."""
    pytest.importorskip("c2pa")
    signed = bytearray(signed_jpeg(signer))
    position = signed.find(b"c2pa")
    assert position > 0
    signed[position + 200] ^= 0xFF
    check = read_bytes(tmp_path, bytes(signed))
    assert check.state == INVALID
    assert check.invalid_reason == CREDENTIALS_FAILED
    assert check.failure_codes == []


def test_re_saving_a_signed_file_removes_the_credentials(tmp_path, signer):
    buffer = io.BytesIO()
    Image.open(io.BytesIO(signed_jpeg(signer))).save(buffer, format="JPEG", quality=80)
    assert read_bytes(tmp_path, buffer.getvalue()).state == UNSIGNED


def test_video(tmp_path, signer):
    pytest.importorskip("cv2")
    path = write_video(tmp_path / "plain.mp4", [((10, 20, 200), 1.0), ((200, 20, 10), 1.0)])
    plain = path.read_bytes()
    assert read_credentials(path, CONFIG).state == UNSIGNED
    signed = sign_bytes(plain, "video/mp4", signer)
    assert read_bytes(tmp_path, signed, name="signed.mp4").state == SIGNED
    changed = bytearray(signed)
    start, end = _box_range(signed, b"mdat")
    changed[(start + end) // 2] ^= 0xFF
    check = read_bytes(tmp_path, bytes(changed), name="changed.mp4")
    assert check.state == INVALID
    assert check.invalid_reason == CONTENT_CHANGED


def test_no_changed_byte_can_alter_what_a_signed_result_reports(tmp_path, signer):
    """Some bytes in the credentials block, such as padding, aren't signed. Changing them must not change the answer."""
    signed = signed_jpeg(signer, source_type="trainedAlgorithmicMedia", extra_assertions=[PRIVATE_ASSERTION])
    start = signed.find(b"jumb") - 4
    end = len(signed) - len(image_bytes())
    original = read_bytes(tmp_path, signed)
    wanted = (original.signer_organisation, original.claim_generator, tuple(original.declared_sources))
    assert original.state == SIGNED
    for offset in range(start, start + (end - start), max(1, (end - start) // 150)):
        changed = bytearray(signed)
        changed[offset] ^= 0x01
        check = read_bytes(tmp_path, bytes(changed))
        if check.state == SIGNED:
            assert (check.signer_organisation, check.claim_generator, tuple(check.declared_sources)) == wanted


def test_measurement_holds_only_counts(tmp_path):
    pytest.importorskip("c2pa")
    pytest.importorskip("cv2")
    real, fake = tmp_path / "real", tmp_path / "fake"
    real.mkdir()
    fake.mkdir()
    for seed in range(3):
        patterned_image(seed + 1).save(real / f"private-real-{seed}.jpg")
        patterned_image(seed + 10).save(fake / f"private-fake-{seed}.png")
    out = tmp_path / "out" / "result.json"
    code = eval_main(
        [
            "--real",
            str(real),
            "--fake",
            str(fake),
            "--out",
            str(out),
            "--source",
            "test|none|",
            "--sample",
            "4",
            "--flips",
            "5",
            "--large-video-mb",
            "1",
            "--sweep-step",
            "5000",
            "--video-sweep-step",
            "100",
        ]
    )
    text = out.read_text(encoding="utf-8")
    document = json.loads(text)
    assert code == 0
    assert "private-" not in text
    assert document["scan"]["images"] == 6
    assert sum(sum(counts.values()) for counts in document["scan"]["by_kind"].values()) == 6
    assert document["known_answers_on_real_images"]["signed_copy"] == {"signed": 4}
    assert document["known_answers_on_real_images"]["re_saved"] == {"unsigned": 4}
    assert document["known_answers_on_real_images"]["byte_changed_in_image_data"] == {"invalid": 4}
    assert document["video"]["byte_changed_in_video_data"]["invalid"] == 5
    assert document["video"]["file_at_upload_limit"]["outcome"] == "signed"
    assert document["video"]["file_at_upload_limit"]["outcome_after_changing_one_byte_in_the_middle"] == "invalid"
    assert document["changing_single_bytes"]["signed_video_credentials_block_every_100_bytes"]["bytes_changed"] > 10
    for sweep in document["changing_single_bytes"].values():
        assert sweep["still_signed_but_report_differs"] == 0


def test_measurement_refuses_bad_input(tmp_path, capsys):
    code = eval_main(["--real", str(tmp_path / "no"), "--fake", str(tmp_path), "--out", str(tmp_path / "o.json"), "--source", "a|b|c"])
    assert code == 2
    assert not (tmp_path / "o.json").exists()
    assert eval_main(["--real", str(tmp_path), "--fake", str(tmp_path), "--out", str(tmp_path / "o.json"), "--source", "bad"]) == 2


# Real signatures whose certificates or format break the standard's rules


MICROSOFT_USAGE = "1.3.6.1.4.1.311.76.59.1.9"
C2PA_CLAIM_USAGE = "1.3.6.1.4.1.62558.2.1"
DOCUMENT_SIGNING_USAGE = "1.3.6.1.5.5.7.3.36"


@pytest.mark.parametrize("usage", [MICROSOFT_USAGE, C2PA_CLAIM_USAGE, DOCUMENT_SIGNING_USAGE])
def test_the_usages_real_signers_declare_are_accepted(tmp_path, signer, usage):
    named = make_signer(usage_oid=usage)
    assert read_bytes(tmp_path, signed_jpeg(named)).state == SIGNED


def test_the_library_default_would_call_those_signatures_invalid(tmp_path, signer):
    """Why the list exists. If the library's default ever changes, this says the list can go."""
    c2pa = pytest.importorskip("c2pa")
    path = write(tmp_path, signed_jpeg(make_signer(usage_oid=MICROSOFT_USAGE)))
    settings = offline_settings()
    del settings["trust"]
    assert module._read_report(path, c2pa, settings)["validation_state"] == "Invalid"


def test_a_usage_not_on_the_list_breaks_the_rules_but_is_not_tampering(tmp_path, signer, monkeypatch):
    signed = signed_jpeg(make_signer(usage_oid=MICROSOFT_USAGE), source_type="trainedAlgorithmicMedia")
    monkeypatch.setattr(module, "_SIGNING_USAGES", DOCUMENT_SIGNING_USAGE)
    check = read_bytes(tmp_path, signed)
    assert check.state == INVALID
    assert check.invalid_reason == RULES_FAILED
    assert check.failure_codes == ["signingCredential.invalid"]
    assert check.signer_trust is None
    assert check.signer_organisation == "Throwaway Test Org"
    assert check.declared_sources == ["trainedAlgorithmicMedia"]


def test_an_expired_certificate_breaks_the_rules_but_is_not_tampering(tmp_path, expired_file):
    check = read_bytes(tmp_path, expired_file)
    assert check.state == INVALID
    assert check.invalid_reason == RULES_FAILED
    assert check.failure_codes == ["signingCredential.expired"]
    assert check.signed_at is None
    assert check.declared_sources == ["trainedAlgorithmicMedia"]


def test_a_malformed_action_list_breaks_the_rules_but_is_not_tampering(tmp_path, signer):
    check = read_bytes(tmp_path, signed_jpeg(signer, first_action="c2pa.edited"))
    assert check.state == INVALID
    assert check.invalid_reason == RULES_FAILED
    assert check.failure_codes == ["assertion.action.malformed"]


def test_an_expired_certificate_and_a_changed_file_counts_as_changed(tmp_path, expired_file):
    changed = bytearray(expired_file)
    changed[-50] ^= 0x01
    check = read_bytes(tmp_path, bytes(changed))
    assert check.invalid_reason == CONTENT_CHANGED
    assert "signingCredential.expired" in check.failure_codes
    assert check.signer_organisation is None
    assert check.declared_sources == []


GOOD_SO_FAR = ["claimSignature.validated", "assertion.dataHash.match"]


def rules_report(failures, passed=tuple(GOOD_SO_FAR), manifest=None):
    data = report("Invalid", failures, manifest if manifest is not None else {"signature_info": {"issuer": "Some Org"}})
    data["validation_results"]["activeManifest"]["success"] = [{"code": code} for code in passed]
    return data


@pytest.mark.parametrize(
    "failures",
    [
        ["signingCredential.expired"],
        ["signingCredential.invalid"],
        ["assertion.action.malformed"],
        ["signingCredential.expired", "assertion.action.malformed"],
    ],
)
def test_rule_failures_keep_what_the_credentials_claim(failures):
    check = interpret(rules_report(failures), trust_checked=False)
    assert check.invalid_reason == RULES_FAILED
    assert check.signer_organisation == "Some Org"


@pytest.mark.parametrize(
    "failures",
    [
        ["signingCredential.revoked"],
        ["signingCredential.expired", "claimSignature.mismatch"],
        ["signingCredential.expired", "assertion.hashedURI.mismatch"],
        ["signingCredential.expired", "some.new.failure"],
    ],
)
def test_any_other_failure_shows_nothing_from_the_credentials(failures):
    check = interpret(rules_report(failures), trust_checked=False)
    assert check.invalid_reason == CREDENTIALS_FAILED
    assert check.signer_organisation is None


@pytest.mark.parametrize("passed", [[], ["claimSignature.validated"], ["assertion.dataHash.match"]])
def test_claims_are_only_shown_if_they_are_tied_to_this_file(passed):
    check = interpret(rules_report(["signingCredential.expired"], passed), trust_checked=False)
    assert check.invalid_reason == CREDENTIALS_FAILED
    assert check.signer_organisation is None


def test_an_expired_certificate_with_a_signing_time_doesnt_mention_a_missing_timestamp():
    manifest = {"signature_info": {"time": "2026-01-02T03:04:05+00:00"}}
    result = analyze_result_with(interpret(rules_report(["signingCredential.expired"], manifest=manifest), trust_checked=False))
    assert "has expired" in result["reasoning"]
    assert "no timestamp" not in result["reasoning"]
    assert "2026-01-02" in result["reasoning"]


# History: AI tools often record their declaration in an earlier manifest


def linked(label):
    return {"relationship": "parentOf", "active_manifest": label}


def chain_report(store, *, deltas=None):
    data = report(manifest=store.pop("newest"))
    data["manifests"].update(store)
    if deltas is not None:
        data["validation_results"]["ingredientDeltas"] = deltas
    return data


def test_a_declaration_in_an_earlier_manifest_is_found():
    data = chain_report({"newest": {"ingredients": [linked("first")]}, "first": actions("trainedAlgorithmicMedia")})
    check = interpret(data, trust_checked=False)
    assert check.declared_sources == []
    assert check.declared_in_history == ["trainedAlgorithmicMedia"]
    assert module.declares_ai(check)


def test_a_chain_is_followed_all_the_way_back():
    data = chain_report(
        {
            "newest": {"ingredients": [linked("middle")]},
            "middle": {**actions("humanEdits"), "ingredients": [linked("first")]},
            "first": actions("trainedAlgorithmicMedia"),
        }
    )
    assert interpret(data, trust_checked=False).declared_in_history == ["humanEdits", "trainedAlgorithmicMedia"]


def test_a_manifest_nothing_links_to_is_ignored():
    data = chain_report({"newest": {}, "stray": actions("trainedAlgorithmicMedia")})
    check = interpret(data, trust_checked=False)
    assert check.declared_in_history == []
    assert not module.declares_ai(check)


def test_loops_in_a_chain_end():
    data = chain_report(
        {
            "newest": {"ingredients": [linked("first"), linked(MANIFEST_ID)]},
            "first": {**actions("humanEdits"), "ingredients": [linked(MANIFEST_ID), linked("first")]},
        }
    )
    assert interpret(data, trust_checked=False).declared_in_history == ["humanEdits"]


def test_a_very_long_chain_is_cut_short():
    store = {f"step{index}": {"ingredients": [linked(f"step{index + 1}")]} for index in range(100)}
    store["step60"] = actions("trainedAlgorithmicMedia")
    store["newest"] = {"ingredients": [linked("step0")]}
    assert interpret(chain_report(store), trust_checked=False).declared_in_history == []


def test_a_source_in_both_is_listed_once():
    data = chain_report({"newest": {**actions("humanEdits"), "ingredients": [linked("first")]}, "first": actions("humanEdits")})
    check = interpret(data, trust_checked=False)
    assert check.declared_sources == ["humanEdits"]
    assert check.declared_in_history == []


def test_history_that_failed_validation_is_not_read():
    failed = [{"validationDeltas": {"failure": [{"code": "claimSignature.mismatch"}]}}]
    data = chain_report({"newest": {"ingredients": [linked("first")]}, "first": actions("trainedAlgorithmicMedia")}, deltas=failed)
    check = interpret(data, trust_checked=False)
    assert check.state == SIGNED
    assert check.declared_in_history == []
    assert check.limitations == [module.HISTORY_FAILED]


def test_history_with_no_failures_is_read():
    clean = [{"validationDeltas": {"failure": [], "success": [{"code": "x"}]}}]
    data = chain_report({"newest": {"ingredients": [linked("first")]}, "first": actions("digitalCapture")}, deltas=clean)
    assert interpret(data, trust_checked=False).declared_in_history == ["digitalCapture"]


def test_a_real_chain_of_two_signed_files(tmp_path, signer):
    made_by_ai = signed_jpeg(signer, source_type="trainedAlgorithmicMedia")
    edited = sign_bytes(image_bytes(seed=2), "image/jpeg", signer, source_type=None, first_action="c2pa.opened", parent=made_by_ai)
    check = read_bytes(tmp_path, edited)
    assert check.state == SIGNED
    assert check.declared_sources == []
    assert check.declared_in_history == ["trainedAlgorithmicMedia"]
    assert module.declares_ai(check)


# A file must never choose who TrustFeed contacts


def test_a_file_pointing_to_a_web_address_is_not_fetched(tmp_path, signer, web_server):
    url, hits = web_server
    pointing = sign_bytes(image_bytes(), "image/jpeg", signer, remote_url=url, embed=False)
    check = read_bytes(tmp_path, pointing)
    assert hits == []
    assert check.status is CheckStatus.UNAVAILABLE
    assert check.state is None
    assert check.limitations == [REMOTE_REASON]
    assert url not in check.model_dump_json()


def test_the_server_would_see_a_fetch_if_one_happened(tmp_path, signer, web_server):
    """The check that makes the test above mean something: with fetching on, the request does arrive."""
    c2pa = pytest.importorskip("c2pa")
    url, hits = web_server
    path = write(tmp_path, sign_bytes(image_bytes(), "image/jpeg", signer, remote_url=url, embed=False))
    settings = {"verify": {"verify_trust": False, "remote_manifest_fetch": True}}
    with pytest.raises(c2pa.C2paError):
        module._read_report(path, c2pa, settings)
    assert hits == ["/manifest.c2pa"]


def test_the_host_block_alone_also_stops_a_fetch(tmp_path, signer, web_server):
    c2pa = pytest.importorskip("c2pa")
    url, hits = web_server
    path = write(tmp_path, sign_bytes(image_bytes(), "image/jpeg", signer, remote_url=url, embed=False))
    settings = offline_settings()
    settings["verify"]["remote_manifest_fetch"] = True
    with pytest.raises(c2pa.C2paError):
        module._read_report(path, c2pa, settings)
    assert hits == []


def test_embedded_credentials_that_also_name_a_web_address_are_read_without_fetching(tmp_path, signer, web_server):
    url, hits = web_server
    both = sign_bytes(image_bytes(), "image/jpeg", signer, remote_url=url)
    assert read_bytes(tmp_path, both).state == SIGNED
    assert hits == []


def test_every_network_route_is_off():
    settings = offline_settings()
    assert settings["core"]["allowed_network_hosts"] == []
    assert settings["core"]["allow_redirects"] is False
    assert settings["core"]["decode_identity_assertions"] is False
    assert settings["verify"]["remote_manifest_fetch"] is False
    assert settings["verify"]["ocsp_fetch"] is False
    assert settings["verify"]["verify_after_reading"] is True


def test_offline_settings_do_not_share_state():
    offline_settings()["verify"]["remote_manifest_fetch"] = True
    offline_settings()["core"]["allowed_network_hosts"].append("example.invalid")
    assert offline_settings()["verify"]["remote_manifest_fetch"] is False
    assert offline_settings()["core"]["allowed_network_hosts"] == []


# Trust list


def trust_config(tmp_path, pem):
    path = tmp_path / "trust.pem"
    path.write_bytes(pem)
    return replace(CONFIG, c2pa_trust_list_path=path)


def test_with_no_trust_list_the_signer_is_not_checked(tmp_path, signer):
    assert read_bytes(tmp_path, signed_jpeg(signer)).signer_trust == NOT_CHECKED


def test_a_signer_on_the_trust_list(tmp_path, signer):
    check = read_bytes(tmp_path, signed_jpeg(signer), trust_config(tmp_path, signer.root_pem))
    assert check.state == SIGNED
    assert check.signer_trust == ON_TRUST_LIST


def test_a_good_signature_from_a_signer_not_on_the_list_is_signed_not_invalid(tmp_path, signer):
    check = read_bytes(tmp_path, signed_jpeg(signer), trust_config(tmp_path, make_signer().root_pem))
    assert check.state == SIGNED
    assert check.signer_trust == NOT_ON_TRUST_LIST
    assert check.failure_codes == []


@pytest.mark.parametrize("contents", [b"not a certificate", b"", b"\xff\xfe\x00"])
def test_an_unusable_trust_list_is_reported_and_never_blames_the_file(tmp_path, signer, contents):
    check = read_bytes(tmp_path, signed_jpeg(signer), trust_config(tmp_path, contents))
    assert check.state == SIGNED
    assert check.signer_trust == NOT_CHECKED
    assert "could not be read" in check.limitations[-1]


def test_a_missing_trust_list_is_reported(tmp_path, signer):
    config = replace(CONFIG, c2pa_trust_list_path=tmp_path / "missing.pem")
    check = read_bytes(tmp_path, signed_jpeg(signer), config)
    assert check.signer_trust == NOT_CHECKED
    assert "could not be read" in check.limitations[-1]


def test_a_trust_list_note_also_reaches_an_unsigned_result(tmp_path):
    pytest.importorskip("c2pa")
    config = replace(CONFIG, c2pa_trust_list_path=tmp_path / "missing.pem")
    check = read_bytes(tmp_path, image_bytes(), config)
    assert check.state == UNSIGNED
    assert "could not be read" in check.limitations[-1]


def test_trust_list_path_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_C2PA_TRUST_LIST", str(tmp_path / "list.pem"))
    assert MediaConfig.from_env().c2pa_trust_list_path == tmp_path / "list.pem"
    monkeypatch.setenv("MEDIA_C2PA_TRUST_LIST", "  ")
    assert MediaConfig.from_env().c2pa_trust_list_path is None


# When it can't run


def test_missing_library_is_reported_and_the_analysis_carries_on(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "c2pa", None)
    path = write(tmp_path, image_bytes())
    check = read_credentials(path, CONFIG)
    assert check.status is CheckStatus.UNAVAILABLE
    assert check.state is None
    assert "c2pa-python" in check.limitations[0]
    result = analyze_media(path, classifier=FakeClassifier(0.5), config=CONFIG)
    assert result.status is CheckStatus.COMPLETE
    assert result.checks.content_credentials.status is CheckStatus.UNAVAILABLE


@pytest.mark.parametrize(
    ("payload", "name"),
    [(b"\x1a\x45\xdf\xa3" + bytes(64), "video.webm"), (b"BM" + bytes(64), "image.bmp"), (b"plain text here" * 10, "note.txt")],
)
def test_a_type_the_library_cant_read_is_unavailable_never_unsigned(tmp_path, payload, name):
    pytest.importorskip("c2pa")
    check = read_bytes(tmp_path, payload, name=name)
    assert check.status is CheckStatus.UNAVAILABLE
    assert check.state is None
    assert "unknown" in check.limitations[0]


def test_a_slow_read_stops_at_the_time_limit(tmp_path, monkeypatch):
    pytest.importorskip("c2pa")
    finish = threading.Event()
    monkeypatch.setattr(module, "_read_report", lambda *args: finish.wait(10))
    started = time.monotonic()
    check = read_bytes(tmp_path, image_bytes(), replace(CONFIG, c2pa_time_limit_s=0.05))
    finish.set()
    assert time.monotonic() - started < 5
    assert check.status is CheckStatus.UNAVAILABLE
    assert "0.05 seconds" in check.limitations[0]


def test_unexpected_errors_are_reported_without_their_message(tmp_path, monkeypatch, caplog):
    pytest.importorskip("c2pa")

    def fail(*args):
        raise RuntimeError("secret-name.jpg contains something private")

    monkeypatch.setattr(module, "_read_report", fail)
    with caplog.at_level(logging.DEBUG):
        check = read_bytes(tmp_path, image_bytes())
    assert check.status is CheckStatus.UNAVAILABLE
    assert "secret" not in check.model_dump_json()
    assert "secret" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_file_names_and_web_addresses_stay_out_of_logs(tmp_path, signer, caplog):
    pointing = sign_bytes(image_bytes(), "image/jpeg", signer, remote_url="http://127.0.0.1:9/private-token", embed=False)
    path = write(tmp_path, pointing, "private-upload-name.jpg")
    with caplog.at_level(logging.DEBUG):
        read_credentials(path, CONFIG)
    assert "private-token" not in caplog.text
    assert "private-upload-name" not in caplog.text


# Reading the library's report


def test_an_untrusted_signer_alone_is_not_a_failure():
    check = interpret(report(failures=["signingCredential.untrusted"]), trust_checked=True)
    assert check.state == SIGNED
    assert check.signer_trust == NOT_ON_TRUST_LIST
    assert check.failure_codes == []


def test_any_other_failure_outweighs_a_valid_state():
    check = interpret(report(failures=["signingCredential.untrusted", "claimSignature.mismatch"]), trust_checked=True)
    assert check.state == INVALID
    assert check.invalid_reason == CREDENTIALS_FAILED
    assert check.failure_codes == ["claimSignature.mismatch"]


@pytest.mark.parametrize("hash_kind", ["dataHash", "bmffHash", "boxesHash", "collectionHash"])
def test_a_content_hash_mismatch_means_the_content_changed(hash_kind):
    check = interpret(report("Invalid", [f"assertion.{hash_kind}.mismatch"]), trust_checked=False)
    assert check.invalid_reason == CONTENT_CHANGED


def test_a_hashed_uri_mismatch_is_not_a_content_change():
    assert interpret(report("Invalid", ["assertion.hashedURI.mismatch"]), trust_checked=False).invalid_reason == CREDENTIALS_FAILED


def test_failure_codes_written_in_a_strange_form_are_not_passed_on():
    check = interpret(report("Invalid", ["<script>alert(1)</script>", "x" * 500]), trust_checked=False)
    assert check.state == INVALID
    assert check.failure_codes == ["unrecognised"]


def test_many_failure_codes_are_capped():
    codes = [f"code.number{index}" for index in range(50)]
    assert len(interpret(report("Invalid", codes), trust_checked=False).failure_codes) == 10


@pytest.mark.parametrize("state", [None, "Unknown", 3, "valid"])
def test_an_unclear_state_is_unavailable(state):
    check = interpret(report(state), trust_checked=False)
    assert check.status is CheckStatus.UNAVAILABLE
    assert check.state is None


def test_trusted_needs_a_manifest_to_describe():
    data = report("Trusted")
    data["active_manifest"] = "something else"
    assert interpret(data, trust_checked=True).status is CheckStatus.UNAVAILABLE


def test_trusted_state_means_on_the_list():
    assert interpret(report("Trusted"), trust_checked=True).signer_trust == ON_TRUST_LIST


@pytest.mark.parametrize(
    "manifest",
    [
        {"assertions": "not a list", "signature_info": 3, "claim_generator_info": [1, "x", None]},
        {"assertions": [1, {"label": 2}, {"label": "c2pa.actions", "data": 5}, {"label": "c2pa.actions", "data": {"actions": [1]}}]},
        {"assertions": [{"label": "c2pa.actions", "data": {"actions": [{"digitalSourceType": 9}]}}], "claim_generator": 7},
    ],
)
def test_odd_manifest_shapes_are_survived(manifest):
    check = interpret(report(manifest=manifest), trust_checked=False)
    assert check.state == SIGNED
    assert check.signer_organisation is None
    assert check.claim_generator is None
    assert check.declared_sources == []


def test_older_manifests_name_the_generator_differently():
    assert interpret(report(manifest={"claim_generator": "Old Tool/1.0"}), trust_checked=False).claim_generator == "Old Tool/1.0"


def test_manifest_text_is_cleaned_and_cut_short():
    manifest = {
        "signature_info": {"issuer": "Good‮evil\x00 <b>Org</b>"},
        "claim_generator_info": [{"name": "y" * 500}],
    }
    check = interpret(report(manifest=manifest), trust_checked=False)
    assert check.signer_organisation == "Goodevil bOrg/b"
    assert check.claim_generator == "y" * 80


def test_text_that_cleans_down_to_nothing_is_null():
    manifest = {"signature_info": {"issuer": " ‮\x00<> "}}
    assert interpret(report(manifest=manifest), trust_checked=False).signer_organisation is None


def test_signing_time_is_kept_only_if_it_is_a_time():
    good = {"signature_info": {"time": "2026-01-02T03:04:05+00:00"}}
    bad = {"signature_info": {"time": "yesterday, trust me"}}
    assert interpret(report(manifest=good), trust_checked=False).signed_at == "2026-01-02T03:04:05+00:00"
    assert interpret(report(manifest=bad), trust_checked=False).signed_at is None


def test_only_known_source_types_are_reported():
    manifest = actions("trainedAlgorithmicMedia", "inventedByTheFileMaker", "digitalCapture", "trainedAlgorithmicMedia")
    assert interpret(report(manifest=manifest), trust_checked=False).declared_sources == [
        "trainedAlgorithmicMedia",
        "digitalCapture",
    ]


def test_source_types_from_elsewhere_are_ignored():
    manifest = {
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {"actions": [{"digitalSourceType": "https://evil.example/digitalsourcetype/digitalCapture"}]},
            }
        ]
    }
    assert interpret(report(manifest=manifest), trust_checked=False).declared_sources == []


@pytest.mark.parametrize("label", ["c2pa.actions", "c2pa.actions.v2", "c2pa.actions__1", "c2pa.actions.v2__2"])
def test_every_form_of_the_actions_label_is_read(label):
    check = interpret(report(manifest=actions("digitalCapture", label=label)), trust_checked=False)
    assert check.declared_sources == ["digitalCapture"]


def test_other_assertions_are_not_read_as_actions():
    check = interpret(report(manifest=actions("digitalCapture", label="my.c2pa.actions")), trust_checked=False)
    assert check.declared_sources == []


# In the full analysis


def analyzed(tmp_path, payload, score=0.1, name="file.jpg"):
    path = write(tmp_path, payload, name)
    return analyze_media(path, classifier=FakeClassifier(score), config=CONFIG)


def test_the_score_and_assessment_never_change(tmp_path, signer):
    plain = analyzed(tmp_path, image_bytes())
    declared = analyzed(tmp_path, signed_jpeg(signer, source_type="trainedAlgorithmicMedia"))
    changed = bytearray(signed_jpeg(signer))
    changed[-50] ^= 0xFF
    broken = analyzed(tmp_path, bytes(changed))
    assert plain.checks.content_credentials.state == UNSIGNED
    assert declared.checks.content_credentials.state == SIGNED
    assert broken.checks.content_credentials.state == INVALID
    for result in (plain, declared, broken):
        assert result.score == 0.1
        assert result.assessment is Assessment.NO_STRONG_SIGNALS


def test_evidence_lines(tmp_path, signer):
    plain = analyzed(tmp_path, image_bytes())
    assert not [line for line in plain.evidence if "Credentials" in line or "credentials" in line]
    declared = analyzed(tmp_path, signed_jpeg(signer, source_type="trainedAlgorithmicMedia"))
    assert "Content Credentials are present and valid: the file has not changed since it was signed." in declared.evidence
    assert "The signed credentials declare AI-generated content." in declared.evidence
    camera = analyzed(tmp_path, signed_jpeg(signer))
    assert "The signed credentials declare AI-generated content." not in camera.evidence
    changed = bytearray(signed_jpeg(signer, source_type="trainedAlgorithmicMedia"))
    changed[-50] ^= 0xFF
    broken = analyzed(tmp_path, bytes(changed))
    assert "Content Credentials are present but did not validate." in broken.evidence
    assert "The signed credentials declare AI-generated content." not in broken.evidence


def test_video_analysis_includes_the_check(tmp_path, signer):
    pytest.importorskip("cv2")
    plain = write_video(tmp_path / "plain.mp4", [((10, 20, 200), 1.0), ((200, 20, 10), 1.0)]).read_bytes()
    result = analyzed(tmp_path, sign_bytes(plain, "video/mp4", signer), name="video.mp4")
    assert result.media_type is MediaType.VIDEO
    assert result.checks.content_credentials.state == SIGNED
    assert credentials_check(result)["result"] == "Signed"


def test_a_rejected_file_reports_the_check_as_not_run(tmp_path):
    result = analyze_media(write(tmp_path, b"not media at all"), classifier=FakeClassifier(0.5), config=CONFIG)
    assert result.checks.content_credentials.status is CheckStatus.UNAVAILABLE
    assert credentials_check(result)["result"] == "Not checked"


# The explanation


def test_unsigned_says_it_proves_nothing(tmp_path):
    pytest.importorskip("c2pa")
    check = credentials_check(analyzed(tmp_path, image_bytes()))
    assert check["check_id"] == "media.c2pa"
    assert check["module"] == "media"
    assert check["status"] == "complete"
    assert check["result"] == "Unsigned"
    assert "This proves nothing" in check["reasoning"]


def test_signed_says_what_it_does_and_doesnt_show(tmp_path, signer):
    check = credentials_check(analyzed(tmp_path, signed_jpeg(signer, source_type="trainedAlgorithmicMedia")))
    assert check["result"] == "Signed"
    assert "'Throwaway Test Org'" in check["reasoning"]
    assert "was not compared with a trust list" in check["reasoning"]
    assert "made by a trained AI model" in check["reasoning"]
    assert "the signer's statement" in check["reasoning"]
    assert "don't show that what it depicts is true" in check_text(check)
    assert "does not change the overall score" in check_text(check)


def test_invalid_doesnt_call_the_media_fake(tmp_path, signer):
    changed = bytearray(signed_jpeg(signer, source_type="trainedAlgorithmicMedia"))
    changed[-50] ^= 0xFF
    check = credentials_check(analyzed(tmp_path, bytes(changed)))
    assert check["result"] == "Invalid"
    assert "has changed since they were signed" in check["reasoning"]
    assert "doesn't show the media is fake" in check["reasoning"]
    assert "Throwaway" not in check_text(check)
    assert "AI model" not in check_text(check)


def test_damaged_credentials_have_their_own_wording(tmp_path, signer):
    changed = bytearray(signed_jpeg(signer, extra_assertions=[PRIVATE_ASSERTION]))
    changed[changed.find(PERSON.encode())] ^= 0x01
    check = credentials_check(analyzed(tmp_path, bytes(changed)))
    assert "damaged or failed validation" in check["reasoning"]


def test_an_expired_certificate_is_explained_without_calling_it_tampering(tmp_path, expired_file):
    result = analyzed(tmp_path, expired_file)
    check = credentials_check(result)
    assert check["result"] == "Invalid"
    assert "has expired and no timestamp shows it was signed before that" in check["reasoning"]
    assert "isn't a sign of tampering" in check["reasoning"]
    assert "doesn't show the media is fake" in check["reasoning"]
    assert "unverified" in check["reasoning"]
    assert "'Throwaway Test Org'" in check["reasoning"]
    assert "made by a trained AI model" in check["reasoning"]
    assert "Those unverified credentials claim AI-generated content." in result.evidence
    assert "The signed credentials declare AI-generated content." not in result.evidence
    assert result.assessment is Assessment.NO_STRONG_SIGNALS


def test_other_rule_failures_are_explained(tmp_path, signer, monkeypatch):
    actions_wrong = credentials_check(analyzed(tmp_path, signed_jpeg(signer, first_action="c2pa.edited")))
    assert "don't follow the standard's format" in actions_wrong["reasoning"]
    signed = signed_jpeg(make_signer(usage_oid=MICROSOFT_USAGE))
    monkeypatch.setattr(module, "_SIGNING_USAGES", DOCUMENT_SIGNING_USAGE)
    usage = credentials_check(analyzed(tmp_path, signed))
    assert "doesn't meet the standard's requirements" in usage["reasoning"]


def test_history_is_explained_separately(tmp_path, signer):
    made_by_ai = signed_jpeg(signer, source_type="trainedAlgorithmicMedia")
    edited = sign_bytes(image_bytes(seed=2), "image/jpeg", signer, source_type="humanEdits", first_action="c2pa.opened", parent=made_by_ai)
    result = analyzed(tmp_path, edited)
    check = credentials_check(result)
    assert "They declare the media was edited by a person." in check["reasoning"]
    assert "Earlier steps in its history declare it was made by a trained AI model." in check["reasoning"]
    assert check["artifacts"][0]["declared_in_history"] == "trainedAlgorithmicMedia"
    assert "The signed credentials declare AI-generated content." in result.evidence


def test_nothing_personal_from_the_manifest_is_reported(tmp_path, signer):
    pytest.importorskip("cryptography")
    named = make_signer(common_name="Personal Certificate Name")
    result = analyzed(tmp_path, signed_jpeg(named, extra_assertions=[PRIVATE_ASSERTION]))
    output = json.dumps([result.model_dump(mode="json"), build_checks(result, config=CONFIG)])
    assert result.checks.content_credentials.state == SIGNED
    assert PERSON not in output
    assert "Personal Certificate Name" not in output
    assert "throwaway test file" not in output
    assert "serial" not in output


def test_the_check_has_the_agreed_shape_and_only_text_artifacts(tmp_path, signer):
    check = credentials_check(analyzed(tmp_path, signed_jpeg(signer)))
    assert set(check) == {"check_id", "module", "label", "status", "result", "reasoning", "benchmark", "artifacts", "limitations"}
    assert check["benchmark"] is None
    assert check["artifacts"][0]["kind"] == "content_credentials"
    assert check["artifacts"][0]["signer_trust"] == NOT_CHECKED
    for artifact in check["artifacts"]:
        assert all(isinstance(key, str) and isinstance(value, str) and value for key, value in artifact.items())


def test_unknown_values_are_left_out_of_artifacts(tmp_path):
    pytest.importorskip("c2pa")
    artifacts = credentials_check(analyzed(tmp_path, image_bytes()))["artifacts"]
    assert artifacts == [{"kind": "content_credentials", "state": UNSIGNED}]


def test_trust_wording(tmp_path, signer):
    signed = signed_jpeg(signer)
    path = write(tmp_path, signed)
    on_list = analyze_media(path, classifier=FakeClassifier(0.1), config=trust_config(tmp_path, signer.root_pem))
    other = analyze_media(path, classifier=FakeClassifier(0.1), config=trust_config(tmp_path, make_signer().root_pem))
    assert "leads to an authority on the trust list" in credentials_check(on_list)["reasoning"]
    assert "doesn't lead to anyone on the trust list" in credentials_check(other)["reasoning"]


def test_large_random_images_also_work(tmp_path, signer):
    """A noisy image makes a large file, closer to a real photo than the patterned ones."""
    pixels = (np.random.default_rng(3).random((1200, 1600, 3)) * 255).astype("uint8")
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="JPEG", quality=95)
    assert read_bytes(tmp_path, sign_bytes(buffer.getvalue(), "image/jpeg", signer)).state == SIGNED
