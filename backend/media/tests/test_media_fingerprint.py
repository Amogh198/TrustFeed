"""Image fingerprints: making them, matching them, and keeping only hashes."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

import pytest
from PIL import Image

from backend.media import MediaConfig, analyze_media
from backend.media.__main__ import main as cli
from backend.media.eval.fingerprints import (
    ALTERATIONS,
    choose_limit,
    main as measure_cli,
    measure,
    rule_matches,
)
from backend.media.explain import FINGERPRINT_RESULTS_PATH, build_checks, load_fingerprint_figures
from backend.media.fingerprint import (
    EXACT_COPY,
    HASH_KINDS,
    LIKELY_SAME_IMAGE,
    MATCH_LIMITS,
    MATCHES_NEEDED,
    CaseFingerprint,
    CaseFingerprintStore,
    QueryFrame,
    compute_fingerprints,
    entry_hashes,
    find_matches,
    fingerprint_distances,
    is_informative,
    looks_like_same_image,
    remember_fingerprints,
)
from backend.media.models import Assessment, CheckStatus
from backend.media.phash import JsonHashIndex, ReferenceEntry, compute_phash
from backend.media.tests.helpers import FakeClassifier, patterned_image, write_video

CONFIG = MediaConfig()


def save(tmp_path, seed=1, name="a.png"):
    path = tmp_path / name
    patterned_image(seed, size=320).save(path)
    return path


def sha_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference(image, **changes):
    hashes = compute_fingerprints(image)
    return ReferenceEntry(
        phash=hashes["phash"],
        label="Old photo",
        first_seen="2019",
        dhash=hashes["dhash"],
        whash=hashes["whash"],
        colorhash=hashes["colorhash"],
        **changes,
    )


def analyzed(path, **options):
    return analyze_media(path, classifier=FakeClassifier(0.5), config=CONFIG, **options)


def explained(result):
    return {check["check_id"]: check for check in build_checks(result, config=CONFIG)}["media.fingerprint"]


# Making fingerprints


def test_every_kind_is_made_and_repeatable():
    image = patterned_image()
    hashes = compute_fingerprints(image)
    assert set(hashes) == set(HASH_KINDS)
    assert hashes == compute_fingerprints(image)
    assert hashes["phash"] == compute_phash(image.convert("RGB"))


def test_different_images_have_different_fingerprints():
    assert compute_fingerprints(patterned_image(1)) != compute_fingerprints(patterned_image(2))


def test_transparent_and_grey_images_can_be_fingerprinted():
    compute_fingerprints(patterned_image().convert("RGBA"))
    compute_fingerprints(patterned_image().convert("L"))


def test_distance_is_zero_for_the_same_and_skips_what_cannot_be_compared():
    hashes = compute_fingerprints(patterned_image())
    assert set(fingerprint_distances(hashes, hashes).values()) == {0}
    assert fingerprint_distances({"phash": "ff"}, {"phash": "ffff"}) == {}
    assert fingerprint_distances({"phash": "ff"}, {"dhash": "ff"}) == {}


# Match rule


def test_limits_in_the_code_come_from_the_published_results():
    rule = load_fingerprint_figures()
    assert rule is not None
    assert rule["limits"] == MATCH_LIMITS
    assert rule["needed"] == MATCHES_NEEDED
    document = json.loads(FINGERPRINT_RESULTS_PATH.read_text(encoding="utf-8"))
    chosen = document["limits_chosen_on_calibration"]
    assert {kind: chosen[kind] for kind in MATCH_LIMITS} == MATCH_LIMITS


def test_colour_alone_never_decides_a_match():
    assert "colorhash" not in MATCH_LIMITS
    assert looks_like_same_image({"colorhash": 0}) is False
    assert looks_like_same_image({"colorhash": 0, "phash": 0}) is False


@pytest.mark.parametrize(
    ("distances", "expected"),
    [
        ({"phash": 17, "dhash": 16}, True),
        ({"phash": 17, "whash": 7}, True),
        ({"dhash": 16, "whash": 7}, True),
        ({"phash": 18, "dhash": 16, "whash": 8}, False),
        ({"phash": 0}, False),
        ({"phash": 18, "dhash": 17}, False),
        ({}, False),
    ],
)
def test_two_kinds_must_agree_within_their_limits(distances, expected):
    assert looks_like_same_image(distances) is expected


def test_a_flat_picture_says_nothing_about_which_picture_it_is():
    flat = compute_fingerprints(Image.new("RGB", (64, 64), (10, 200, 30)))
    assert is_informative(flat) is False
    assert is_informative(compute_fingerprints(patterned_image())) is True
    assert is_informative({}) is False
    other_flat = compute_fingerprints(Image.new("RGB", (64, 64), (200, 10, 30)))
    entry = ReferenceEntry(phash=other_flat["phash"], label="x", dhash=other_flat["dhash"], whash=other_flat["whash"])
    assert find_matches(None, [QueryFrame(None, flat)], [entry], []) == []


# Finding matches


def test_exact_file_is_an_exact_copy_and_outranks_a_visual_match():
    image = patterned_image()
    hashes = compute_fingerprints(image)
    visual = reference(image)
    exact = reference(patterned_image(2), sha256="a" * 64)
    matches = find_matches("a" * 64, [QueryFrame(None, hashes)], [visual, exact], [])
    assert [m.kind for m in matches] == [EXACT_COPY, LIKELY_SAME_IMAGE]


def test_changed_copy_is_a_likely_match_and_a_different_image_is_not():
    image = patterned_image(1, size=512)
    copy = compute_fingerprints(ALTERATIONS["recompressed_low_quality"](image))
    assert [m.kind for m in find_matches(None, [QueryFrame(None, copy)], [reference(image)], [])] == [LIKELY_SAME_IMAGE]
    other = compute_fingerprints(patterned_image(9, size=512))
    assert find_matches(None, [QueryFrame(None, other)], [reference(image)], []) == []


def test_older_reference_with_only_a_phash_is_not_matched_here():
    image = patterned_image()
    hashes = compute_fingerprints(image)
    older = ReferenceEntry(phash=hashes["phash"], label="Old")
    assert entry_hashes(older) == {"phash": hashes["phash"]}
    assert find_matches(None, [QueryFrame(None, hashes)], [older], []) == []


def test_earlier_case_matches_by_file_or_by_picture():
    image = patterned_image()
    hashes = compute_fingerprints(image)
    by_file = CaseFingerprint(case_id="c1", seen_at="2026-01-01", sha256="b" * 64)
    by_picture = CaseFingerprint(case_id="c2", seen_at="2026-01-02", frames=[hashes])
    unrelated = CaseFingerprint(case_id="c3", seen_at="2026-01-03", frames=[compute_fingerprints(patterned_image(9))])
    matches = find_matches("b" * 64, [QueryFrame(None, hashes)], [], [by_file, by_picture, unrelated])
    assert [(m.case_id, m.kind, m.found_in) for m in matches] == [
        ("c1", EXACT_COPY, "earlier_case"),
        ("c2", LIKELY_SAME_IMAGE, "earlier_case"),
    ]


def test_closest_frame_gives_the_timestamp():
    image = patterned_image()
    frames = [QueryFrame(1.0, compute_fingerprints(patterned_image(9))), QueryFrame(4.0, compute_fingerprints(image))]
    assert find_matches(None, frames, [reference(image)], [])[0].timestamp_s == 4.0


def test_when_several_frames_match_the_closest_one_is_reported():
    image = patterned_image(size=512)
    exact = compute_fingerprints(image)
    changed = dict(exact, phash=f"{int(exact['phash'], 16) ^ 0b1111:016x}")
    frames = [QueryFrame(1.0, changed), QueryFrame(4.0, exact), QueryFrame(7.0, changed)]
    match = find_matches(None, frames, [reference(image)], [])[0]
    assert match.timestamp_s == 4.0
    assert match.distances["phash"] == 0


@pytest.mark.parametrize(
    ("query_dhash", "target_dhash"),
    [("0000000000000003", "000000000000000f"), ("000000000000000f", "0000000000000003")],
)
def test_either_side_being_almost_blank_stops_a_match(query_dhash, target_dhash):
    # Both sides agree closely, but one side has too little detail for that to mean anything.
    shared = {"phash": "aaaaaaaaaaaaaaaa", "whash": "aaaaaaaaaaaaaaaa"}
    entry = ReferenceEntry(label="x", dhash=target_dhash, **shared)
    assert find_matches(None, [QueryFrame(None, {**shared, "dhash": query_dhash})], [entry], []) == []
    informative = "00000000000000ff"
    entry = ReferenceEntry(label="x", dhash=informative, **shared)
    assert len(find_matches(None, [QueryFrame(None, {**shared, "dhash": informative})], [entry], [])) == 1


# In the analysis


def test_image_result_has_the_file_hash_and_every_fingerprint(tmp_path):
    path = save(tmp_path)
    check = analyzed(path).checks.fingerprint
    assert check.status is CheckStatus.COMPLETE
    assert check.sha256 == sha_of(path)
    assert set(check.hashes) == set(HASH_KINDS)
    assert check.compared is False
    assert check.matches == []


def test_match_in_the_reference_list_is_found(tmp_path):
    path = save(tmp_path)
    with Image.open(path) as image:
        index = JsonHashIndex([reference(image)])
    result = analyzed(path, hash_index=index)
    check = result.checks.fingerprint
    assert check.references_checked == 1
    assert check.matches[0].kind == LIKELY_SAME_IMAGE
    assert check.matches[0].label == "Old photo"
    assert any("look like the same image as reference 'Old photo'" in line for line in result.evidence)


def test_fingerprints_do_not_change_the_score_or_assessment(tmp_path):
    path = save(tmp_path)
    with Image.open(path) as image:
        # A changed phash, so that the separate pHash check finds nothing, but dhash and whash still agree.
        entry = reference(image).model_copy(update={"phash": "0" * 16})
    result = analyzed(path, hash_index=JsonHashIndex([entry]))
    assert result.checks.fingerprint.matches
    assert result.checks.phash.matches == []
    assert result.score == 0.5
    assert result.assessment is Assessment.INCONCLUSIVE


def test_bad_earlier_case_store_is_reported_and_analysis_continues(tmp_path):
    path = save(tmp_path)
    broken = tmp_path / "cases.json"
    broken.write_text("{not json", encoding="utf-8")
    config = MediaConfig(case_fingerprints_path=broken)
    result = analyze_media(path, classifier=FakeClassifier(0.5), config=config)
    assert result.checks.fingerprint.status is CheckStatus.COMPLETE
    assert "could not be read" in " ".join(result.checks.fingerprint.limitations)
    assert result.score == 0.5


def test_failed_fingerprint_keeps_the_file_hash_and_other_checks(tmp_path, monkeypatch):
    path = save(tmp_path)

    def fail(image):
        raise RuntimeError("private detail")

    monkeypatch.setattr("backend.media.analyzer.compute_fingerprints", fail)
    result = analyzed(path)
    check = result.checks.fingerprint
    assert check.sha256 == sha_of(path)
    assert check.hashes == {}
    assert "could not be computed" in " ".join(check.limitations)
    assert "private detail" not in " ".join(check.limitations)
    assert result.score == 0.5


def test_rejected_input_makes_no_fingerprints(tmp_path):
    result = analyzed(tmp_path / "missing.png")
    assert result.checks.fingerprint.status is CheckStatus.UNAVAILABLE
    assert explained(result)["result"] == "No fingerprints"


def test_each_video_keyframe_is_fingerprinted(tmp_path):
    video = write_video(tmp_path / "clip.mp4", [((0, 0, 255), 2.0), ((255, 0, 0), 2.0)])
    result = analyzed(video)
    assert all(set(frame.fingerprints) == set(HASH_KINDS) for frame in result.checks.keyframes.frames)
    check = result.checks.fingerprint
    assert check.frames_hashed == len(result.checks.keyframes.frames)
    assert check.sha256 == sha_of(video)
    assert check.hashes == {}


def test_two_flat_videos_are_not_called_the_same_but_the_same_file_is(tmp_path):
    first = write_video(tmp_path / "a.mp4", [((0, 0, 255), 2.0)])
    second = write_video(tmp_path / "b.mp4", [((0, 255, 0), 2.0)])
    store_path = tmp_path / "cases.json"
    remember_fingerprints(analyzed(first), "case-1", store_path)
    store = CaseFingerprintStore.load(store_path)
    assert analyzed(second, case_store=store).checks.fingerprint.matches == []
    assert [m.kind for m in analyzed(first, case_store=store).checks.fingerprint.matches] == [EXACT_COPY]


# Keeping only hashes


def test_store_holds_only_hashes_and_a_date(tmp_path):
    path = save(tmp_path, name="secret-name.png")
    store_path = tmp_path / "cases.json"
    assert remember_fingerprints(analyzed(path), "case-1", store_path, seen_at="2026-11-05") is True
    text = store_path.read_text(encoding="utf-8")
    assert "secret-name" not in text
    assert str(tmp_path).replace("\\", "\\\\") not in text
    entry = json.loads(text)["entries"][0]
    assert set(entry) == {"case_id", "seen_at", "sha256", "frames"}
    assert all(set(frame) == set(HASH_KINDS) for frame in entry["frames"])
    assert len(text) < 1000


def test_earlier_case_is_found_later_and_can_be_removed(tmp_path):
    path = save(tmp_path)
    store_path = tmp_path / "cases.json"
    remember_fingerprints(analyzed(path), "case-1", store_path, seen_at="2026-11-05")
    store = CaseFingerprintStore.load(store_path)
    match = analyzed(path, case_store=store).checks.fingerprint.matches[0]
    assert (match.kind, match.case_id, match.first_seen) == (EXACT_COPY, "case-1", "2026-11-05")
    assert store.remove("case-1") is True
    assert store.remove("case-1") is False
    assert analyzed(path, case_store=store).checks.fingerprint.matches == []


def test_remembering_a_case_again_replaces_it(tmp_path):
    path = save(tmp_path)
    store_path = tmp_path / "cases.json"
    remember_fingerprints(analyzed(path), "case-1", store_path, seen_at="first")
    remember_fingerprints(analyzed(path), "case-1", store_path, seen_at="second")
    store = CaseFingerprintStore.load(store_path)
    assert [entry.seen_at for entry in store.entries] == ["second"]


def test_rejected_input_is_not_remembered(tmp_path):
    store_path = tmp_path / "cases.json"
    assert remember_fingerprints(analyzed(tmp_path / "missing.png"), "case-1", store_path) is False
    assert not store_path.exists()


def test_missing_store_is_empty_and_malformed_entries_are_counted(tmp_path):
    assert len(CaseFingerprintStore.load(tmp_path / "none.json")) == 0
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"entries": [{"case_id": "a", "seen_at": "b"}, {"nope": 1}]}), encoding="utf-8")
    store = CaseFingerprintStore.load(path)
    assert (len(store), store.skipped) == (1, 1)


# Explanation check


def test_check_never_calls_a_fingerprint_a_signature_or_a_match_the_source(tmp_path):
    path = save(tmp_path)
    with Image.open(path) as image:
        check = explained(analyzed(path, hash_index=JsonHashIndex([reference(image)])))
    limitations = " ".join(check["limitations"])
    assert "A fingerprint is not a signature." in limitations
    text = f"{check['result']} {check['reasoning']}".casefold()
    assert "signature" not in text
    assert "the source" not in text
    assert "the original" not in text


def test_check_reports_measured_figures_including_what_it_misses(tmp_path):
    check = explained(analyzed(save(tmp_path)))
    rule = load_fingerprint_figures()
    mirrored = rule["copies_matched"]["mirrored"]
    assert f"{mirrored['count']} of {mirrored['total']} mirrored copies" in check["reasoning"]
    wrong = rule["false_match_rate"]
    assert f"{wrong['count']} of {wrong['total']} unrelated pairs" in check["reasoning"]
    assert check["benchmark"] is None


def test_nothing_to_compare_is_not_called_a_clean_result(tmp_path):
    check = explained(analyzed(save(tmp_path)))
    assert check["result"] == "Made, not compared"
    assert "found nothing either way" in check["reasoning"]


def test_no_match_says_what_it_cannot_show(tmp_path):
    entry = reference(patterned_image(9))
    check = explained(analyzed(save(tmp_path), hash_index=JsonHashIndex([entry])))
    assert check["result"] == "No match in 1 references and 0 earlier cases"
    assert "doesn't show the media is new" in check["reasoning"]


def test_artifacts_hold_only_text(tmp_path):
    path = save(tmp_path)
    with Image.open(path) as image:
        check = explained(analyzed(path, hash_index=JsonHashIndex([reference(image)])))
    assert [artifact["kind"] for artifact in check["artifacts"]] == ["fingerprints", "fingerprint_match"]
    assert all(isinstance(value, str) for artifact in check["artifacts"] for value in artifact.values())
    json.dumps(check)


def test_results_that_do_not_match_the_rule_in_use_are_not_shown(tmp_path):
    document = json.loads(FINGERPRINT_RESULTS_PATH.read_text(encoding="utf-8"))
    document["test_split"]["any_two_structural"]["limits"]["phash"] = 3
    path = tmp_path / "results.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert load_fingerprint_figures(path) is None
    assert load_fingerprint_figures(tmp_path / "none.json") is None
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_fingerprint_figures(broken) is None


# Command line


def test_index_add_stores_every_fingerprint_and_the_file_hash(tmp_path):
    path = save(tmp_path)
    index_path = tmp_path / "i.json"
    assert cli(["index-add", str(path), "--index", str(index_path), "--label", "Reference"]) == 0
    entry = JsonHashIndex.load(index_path).entries[0]
    assert entry.sha256 == sha_of(path)
    assert entry.dhash and entry.whash and entry.colorhash


def test_cli_remembers_and_then_finds_a_case(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("backend.media.analyzer.default_classifier", lambda config: FakeClassifier(0.5))
    path = save(tmp_path)
    cases = tmp_path / "cases.json"
    assert cli(["analyze", str(path), "--cases", str(cases), "--remember", "case-1"]) == 0
    capsys.readouterr()
    assert cli(["analyze", str(path), "--cases", str(cases)]) == 0
    decoded = json.loads(capsys.readouterr().out)
    assert decoded["checks"]["fingerprint"]["matches"][0]["case_id"] == "case-1"


def test_cli_remember_needs_a_store(tmp_path, capsys):
    assert cli(["analyze", str(save(tmp_path)), "--remember", "case-1"]) == 2
    assert "--remember needs --cases" in capsys.readouterr().err


# Measuring


def test_limit_stops_where_unrelated_images_start_to_match():
    unrelated = Counter({0: 0, 5: 1, 6: 1, 7: 8})
    assert choose_limit(unrelated, 1000, target=0.001) == 5
    assert choose_limit(unrelated, 10, target=0.001) == 4
    assert choose_limit(Counter({0: 5}), 1000, target=0.001) is None
    assert choose_limit(Counter(), 0) is None


def test_rule_counts_only_kinds_with_a_limit():
    limits = {"phash": 3, "dhash": None}
    assert rule_matches({"phash": 3, "dhash": 0}, limits, ("phash", "dhash"), 1) is True
    assert rule_matches({"phash": 3, "dhash": 0}, limits, ("phash", "dhash"), 2) is False


@pytest.mark.parametrize("name", list(ALTERATIONS))
def test_alterations_leave_the_callers_image_alone_and_give_a_picture(name):
    image = patterned_image(size=200)
    before = image.tobytes()
    copy = ALTERATIONS[name](image)
    assert image.tobytes() == before
    assert copy.size[0] > 0


def folders(tmp_path):
    real, fake = tmp_path / "real", tmp_path / "fake"
    for folder, seeds in ((real, range(1, 7)), (fake, range(7, 13))):
        folder.mkdir()
        for seed in seeds:
            patterned_image(seed, size=128).save(folder / f"{seed}.png")
    return real, fake


def test_measurement_holds_no_file_names_and_chooses_on_calibration(tmp_path):
    real, fake = folders(tmp_path)
    result = measure(real, fake, sources=[{"name": "t", "licence": "CC0", "url": ""}])
    assert result["dataset"]["images"] == 12
    assert set(result["test_split"]["any_two_structural"]["copies_matched"]) == set(ALTERATIONS)
    assert result["settings"]["target_false_match_rate"] == 0.001
    text = json.dumps(result)
    assert ".png" not in text
    assert str(tmp_path).replace("\\", "\\\\") not in text


def test_measurement_command_refuses_bad_input(tmp_path, capsys):
    out = tmp_path / "o.json"
    assert measure_cli(["--real", str(tmp_path / "x"), "--fake", str(tmp_path), "--out", str(out), "--source", "a|b|c"]) == 2
    assert measure_cli(["--real", str(tmp_path), "--fake", str(tmp_path), "--out", str(out), "--source", "bad"]) == 2
    assert not out.exists()
