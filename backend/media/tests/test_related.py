"""Linking cases that hold the same picture, how far links reach and what each one shows. No network is used."""

import json
from pathlib import Path

import pytest

from backend.media import analyze_media
from backend.media.fingerprint import CaseFingerprint, compute_fingerprints, fingerprint_record
from backend.media.related import (
    MAX_LINKS_FROM_START,
    SHARES_CONTENT,
    add_earlier_matches,
    related_cases,
)
from backend.media.tests.helpers import FakeClassifier, patterned_image

A = {"phash": "ffffffffffffffff", "dhash": "ffffffffffffffff", "whash": "ffffffffffffffff"}


def hashes_away(flips: int) -> dict[str, str]:
    """Hashes that differ from ``A`` in this many bits per kind."""
    value = format((1 << 64) - 1 - ((1 << flips) - 1), "016x")
    return {"phash": value, "dhash": value, "whash": value}


def record(case_id, hashes, seen_at="2026-11-01T00:00:00", sha256=None, features=()):
    return CaseFingerprint(case_id=case_id, seen_at=seen_at, sha256=sha256, frames=[hashes] if hashes else [], local_features=list(features))


def real(seed, crop=0):
    image = patterned_image(seed, 512).convert("RGB")
    if crop:
        image = image.crop((crop, crop, 512 - crop, 512 - crop))
    return compute_fingerprints(image)


def test_a_changed_copy_is_linked_and_says_which_hashes_agreed():
    found = related_cases(record("start", real(1)), [record("copy", real(1, 12)), record("other", real(2))])
    assert [item.case_id for item in found] == ["copy"]
    assert found[0].through_case_id is None
    assert found[0].links_from_start == 1
    assert {"phash", "dhash", "whash"} <= set(found[0].distances)


def test_the_same_file_is_an_exact_copy():
    found = related_cases(record("start", None, sha256="abc"), [record("same", None, sha256="abc")])
    assert [(item.case_id, item.kind) for item in found] == [("same", "exact_copy")]


def test_a_chain_says_what_it_went_through_and_stops_at_the_cap():
    # Each record is close to the next one, but too far from any record two steps away.
    chain = [record(f"c{index}", hashes_away(index * 14)) for index in range(5)]
    assert MAX_LINKS_FROM_START == 2
    found = {item.case_id: item for item in related_cases(chain[0], chain[1:])}
    assert set(found) == {"c1", "c2"}
    assert found["c1"].through_case_id is None
    assert found["c2"].through_case_id == "c1"
    assert found["c2"].links_from_start == 2


def test_a_case_never_links_to_itself():
    assert related_cases(record("start", real(1)), [record("start", real(1))]) == []


def test_the_oldest_comes_first():
    found = related_cases(
        record("start", real(1)),
        [record("new", real(1), "2026-11-03T00:00:00"), record("old", real(1), "2026-11-01T00:00:00")],
    )
    assert [item.case_id for item in found] == ["old", "new"]


def _features(seed, crop=0):
    pytest.importorskip("cv2")
    from backend.media.local_features import compute_features

    image = real_picture(seed)
    if crop:
        image = image.crop((crop, crop, image.width - crop, image.height - crop))
    text = compute_features(image)
    assert text
    return text


def real_picture(seed):
    """A picture with fine detail, unlike the smooth test pattern, so it has patches to compare."""
    import numpy as np
    from PIL import Image

    generator = np.random.default_rng(seed)
    blocks = generator.integers(0, 256, (48, 48, 3), dtype=np.uint8)
    return Image.fromarray(blocks).resize((640, 640), Image.Resampling.NEAREST)


def test_local_features_link_a_heavy_crop_that_hashes_miss():
    pytest.importorskip("cv2")
    original, cropped = real_picture(5), real_picture(5).crop((128, 128, 512, 512))
    assert related_cases(record("start", compute_fingerprints(original)), [record("crop", compute_fingerprints(cropped))]) == []
    found = related_cases(
        record("start", compute_fingerprints(original), features=[_features(5)]),
        [record("crop", compute_fingerprints(cropped), features=[_features(5, 128)]), record("other", None, features=[_features(6)])],
    )
    assert [(item.case_id, item.kind) for item in found] == [("crop", SHARES_CONTENT)]
    assert found[0].agreeing_features >= 9


def test_local_feature_matches_never_lead_onward_through_another_case():
    pytest.importorskip("cv2")
    # "bridge" shares content with the start, and "beyond" has the same hashes as "bridge".
    bridge_hashes = real(3)
    found = related_cases(
        record("start", real(1), features=[_features(5)]),
        [record("bridge", bridge_hashes, features=[_features(5, 128)]), record("beyond", bridge_hashes)],
    )
    assert [item.case_id for item in found] == ["bridge"]


def _analysis(tmp_path, seed=1):
    path = tmp_path / f"p{seed}.png"
    real_picture(seed).save(path)
    return analyze_media(path, classifier=FakeClassifier(0.1))


def test_a_match_adds_evidence_and_never_changes_the_score(tmp_path):
    pytest.importorskip("imagehash")
    alone = _analysis(tmp_path)
    linked = _analysis(tmp_path)
    earlier = fingerprint_record(alone, "earlier", "2026-11-01T00:00:00")
    add_earlier_matches(linked, [earlier])
    assert linked.score == alone.score
    assert linked.assessment == alone.assessment
    assert [match.case_id for match in linked.checks.fingerprint.matches] == ["earlier"]
    assert any("earlier case 'earlier'" in line for line in linked.evidence)


def test_local_features_are_kept_out_of_responses_and_the_hash_file(tmp_path):
    pytest.importorskip("cv2")
    from backend.media.fingerprint import CaseFingerprintStore, remember_fingerprints

    result = _analysis(tmp_path)
    assert result.checks.fingerprint.local_features
    assert "local_features" not in json.dumps(result.model_dump(mode="json"))
    assert fingerprint_record(result, "case", "2026-11-01T00:00:00").local_features
    store_path = tmp_path / "cases.json"
    assert remember_fingerprints(result, "case", store_path)
    assert CaseFingerprintStore.load(store_path).entries[0].local_features == []


def test_broken_saved_features_count_as_no_match():
    pytest.importorskip("cv2")
    from backend.media.local_features import agreeing_features

    assert agreeing_features("not base64!", _features(5)) == 0
    assert agreeing_features("QUJD", _features(5)) == 0


def test_the_saved_limit_is_the_one_chosen_on_the_calibration_split():
    from backend.media.local_features import MATCH_LIMIT

    results = Path(__file__).resolve().parents[3] / "data" / "eval" / "crop_matching_2026-11-06.json"
    assert json.loads(results.read_text(encoding="utf-8"))["limit_chosen_on_calibration"] == MATCH_LIMIT
