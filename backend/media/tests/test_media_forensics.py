from __future__ import annotations

import io
import json
import logging
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.media import MediaConfig, analyze_media, forensics
from backend.media import explain as explain_module
from backend.media.eval import forensics as evaluation
from backend.media.forensics import (
    COMPRESSION_GHOST,
    ELA,
    FLAG_LIMITS,
    FREQUENCY_DETAIL,
    FREQUENCY_PEAKS,
    JPEG_ONLY,
    NOISE_LEVEL,
    NOISE_UNEVENNESS,
    TEST_NAMES,
    Measurement,
    block_means,
    estimate_jpeg_quality,
    find_regions,
    measure_all,
    robust_z,
    run_forensics,
)
from backend.media.models import CheckStatus, ForensicRegion, ForensicsCheck, ForensicTest
from backend.media.tests.helpers import FakeClassifier, write_video

RESULTS = Path(__file__).resolve().parents[3] / "data" / "eval" / "forensics_2026-11-06.json"


def natural_image(seed: int = 1, size: int = 256, noise: float = 6.0) -> Image.Image:
    """Smooth shapes with camera-like noise, so the tests have realistic blocks to read."""
    generator = np.random.default_rng(seed)
    y, x = np.indices((size, size), dtype=np.float32)
    base = 120 + 50 * np.sin(x / 37 + seed) * np.cos(y / 23)
    pixels = np.stack([base, base * 0.9 + 10, base * 0.8 + 20], axis=2) + generator.normal(0, noise, (size, size, 3))
    return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))


def saved(image: Image.Image, path: Path, **options) -> Path:
    image.save(path, **options)
    return path


def jpeg_copy(image: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    with Image.open(buffer) as reopened:
        return reopened.convert("RGB")


def by_name(check: ForensicsCheck) -> dict[str, ForensicTest]:
    return {test.name: test for test in check.tests}


# The measurements.


def test_every_test_gives_a_finite_score_and_repeats_exactly():
    pixels = np.asarray(natural_image(), dtype=np.uint8)
    first, second = measure_all(pixels), measure_all(pixels)
    assert set(first) == set(TEST_NAMES)
    for name in TEST_NAMES:
        assert np.isfinite(first[name].score)
        assert first[name].score == second[name].score


def test_only_tests_that_mark_regions_return_a_block_map():
    measured = measure_all(np.asarray(natural_image(), dtype=np.uint8))
    with_maps = {name for name, value in measured.items() if value.block_z is not None}
    assert with_maps == {ELA, NOISE_UNEVENNESS, COMPRESSION_GHOST}


def test_block_means_averages_each_block_and_drops_the_leftover_edge():
    values = np.arange(36, dtype=np.float32).reshape(6, 6)
    means = block_means(values, 3)
    assert means.shape == (2, 2)
    assert means[0, 0] == pytest.approx(values[:3, :3].mean())


def test_robust_z_is_not_hidden_by_the_outlier_itself():
    values = np.array([1.0, 1.1, 0.9, 1.0, 1.1, 0.9, 50.0])
    z = robust_z(values)
    assert z[-1] > 100
    assert abs(z[0]) < 2


def test_robust_z_of_a_flat_area_does_not_divide_by_zero():
    assert np.all(robust_z(np.ones((4, 4))) == 0)


def test_robust_z_can_ignore_masked_values_when_finding_the_middle():
    values = np.array([1.0, 1.1, 0.9, 500.0, 500.0, 500.0, 500.0])
    mask = np.array([True, True, True, False, False, False, False])
    assert robust_z(values, mask=mask)[0] == pytest.approx(0.0)


def test_noise_level_reads_higher_for_a_cleaner_image():
    clean = measure_all(np.asarray(natural_image(noise=1.0), dtype=np.uint8))[NOISE_LEVEL].score
    noisy = measure_all(np.asarray(natural_image(noise=12.0), dtype=np.uint8))[NOISE_LEVEL].score
    assert clean > noisy


def test_uneven_noise_reads_higher_when_one_patch_is_much_noisier():
    image = natural_image(noise=2.0, size=512)
    pixels = np.asarray(image, dtype=np.float32).copy()
    pixels[128:256, 128:256] += np.random.default_rng(3).normal(0, 25, (128, 128, 3))
    patched = np.clip(pixels, 0, 255).astype(np.uint8)
    plain = measure_all(np.asarray(image, dtype=np.uint8))[NOISE_UNEVENNESS].score
    assert measure_all(patched)[NOISE_UNEVENNESS].score > plain


def test_a_noisier_patch_is_marked_where_it_is():
    pixels = np.asarray(natural_image(noise=2.0, size=512), dtype=np.float32).copy()
    pixels[128:256, 128:256] += np.random.default_rng(3).normal(0, 25, (128, 128, 3))
    measured = measure_all(np.clip(pixels, 0, 255).astype(np.uint8))[NOISE_UNEVENNESS]
    regions = find_regions(measured.block_z, measured.block_size)
    assert regions
    box = regions[0]
    assert box.x <= 128 and box.y <= 128
    assert box.x + box.width >= 256 and box.y + box.height >= 256


def test_detail_reads_higher_for_a_blurred_image():
    sharp = natural_image(noise=8.0)
    blurred = sharp.resize((128, 128), Image.Resampling.BILINEAR).resize((256, 256), Image.Resampling.BILINEAR)
    assert (
        measure_all(np.asarray(blurred, dtype=np.uint8))[FREQUENCY_DETAIL].score
        > measure_all(np.asarray(sharp, dtype=np.uint8))[FREQUENCY_DETAIL].score
    )


def test_regular_peaks_read_higher_when_a_fine_pattern_is_added():
    image = natural_image(noise=4.0, size=512)
    y, x = np.indices((512, 512), dtype=np.float32)
    pattern = (6 * np.sin(2 * np.pi * x * 0.31) * np.sin(2 * np.pi * y * 0.23))[..., None]
    patterned = np.clip(np.asarray(image, dtype=np.float32) + pattern, 0, 255).astype(np.uint8)
    plain = measure_all(np.asarray(image, dtype=np.uint8))[FREQUENCY_PEAKS].score
    assert measure_all(patterned)[FREQUENCY_PEAKS].score > plain


def test_a_jpeg_shows_a_stronger_grid_than_the_same_pixels_before_saving():
    image = natural_image(noise=1.0)
    grid = forensics.COMPRESSION_GRID
    before = measure_all(np.asarray(image, dtype=np.uint8))[grid].score
    assert measure_all(np.asarray(jpeg_copy(image, 40), dtype=np.uint8))[grid].score > before


def test_a_flat_image_does_not_crash_any_test():
    measured = measure_all(np.full((128, 128, 3), 128, dtype=np.uint8))
    for name in TEST_NAMES:
        assert measured[name].score is None or np.isfinite(measured[name].score)


def test_an_all_black_image_has_no_usable_noise():
    measured = measure_all(np.zeros((128, 128, 3), dtype=np.uint8))
    assert measured[NOISE_LEVEL].score is None
    assert measured[NOISE_UNEVENNESS].score is None


def test_frequency_tests_need_enough_pixels():
    measured = measure_all(np.asarray(natural_image(size=100), dtype=np.uint8))
    assert measured[FREQUENCY_DETAIL].score is None
    assert measured[FREQUENCY_PEAKS].score is None


# Regions.


def _blob_map(rows: int = 20, columns: int = 20) -> np.ndarray:
    z = np.zeros((rows, columns))
    z[5:9, 3:7] = 9
    return z


def test_regions_are_given_in_image_pixels():
    assert find_regions(_blob_map(), 16) == [ForensicRegion(x=48, y=80, width=64, height=64)]


def test_regions_are_moved_by_the_origin_when_only_the_middle_was_examined():
    assert find_regions(_blob_map(), 16, (100, 200))[0] == ForensicRegion(x=148, y=280, width=64, height=64)


def test_a_few_stray_blocks_are_not_a_region():
    z = np.zeros((20, 20))
    z[5, 5] = z[5, 6] = 9
    assert find_regions(z, 16) == []


def test_a_region_covering_most_of_the_image_says_nothing_about_any_part():
    z = np.zeros((20, 20))
    z[1:19, 1:19] = 9
    assert find_regions(z, 16) == []


def test_only_the_largest_regions_are_kept_largest_first():
    z = np.zeros((40, 40))
    for index in range(7):
        z[index * 5 + 1 : index * 5 + 4, 1 : 3 + index] = 9
    regions = find_regions(z, 1)
    assert len(regions) == forensics.MAX_REGIONS
    areas = [region.width * region.height for region in regions]
    assert areas == sorted(areas, reverse=True)
    assert areas[0] == 3 * 8


# JPEG quality.


@pytest.mark.parametrize("quality", [30, 50, 75, 90, 95])
def test_jpeg_quality_estimate_matches_the_setting_used(tmp_path, quality):
    path = saved(natural_image(), tmp_path / "a.jpg", quality=quality)
    with Image.open(path) as image:
        assert abs(estimate_jpeg_quality(image.quantization[0]) - quality) <= 1


@pytest.mark.parametrize("table", [None, [], [1, 2, 3], [0] * 64])
def test_jpeg_quality_estimate_is_null_for_a_table_it_cannot_read(table):
    assert estimate_jpeg_quality(table) is None


# The check.


def test_a_jpeg_gets_every_test(tmp_path):
    path = saved(natural_image(), tmp_path / "a.jpg", quality=80)
    with Image.open(path) as image:
        check = run_forensics(path, image.convert("RGB"), "jpeg", MediaConfig())
    assert check.status is CheckStatus.COMPLETE
    assert [test.name for test in check.tests] == list(TEST_NAMES)
    assert all(test.status is CheckStatus.COMPLETE for test in check.tests)
    assert check.source_format == "jpeg"
    assert abs(check.jpeg_quality_estimate - 80) <= 1


def test_compression_tests_do_not_run_on_a_png_and_say_why(tmp_path):
    path = saved(natural_image(), tmp_path / "a.png")
    with Image.open(path) as image:
        check = run_forensics(path, image.convert("RGB"), "png", MediaConfig())
    assert check.jpeg_quality_estimate is None
    for test in check.tests:
        if test.name in JPEG_ONLY:
            assert test.status is CheckStatus.UNAVAILABLE
            assert "JPEG" in test.reason
            assert test.score is None and test.flagged is None
        else:
            assert test.status is CheckStatus.COMPLETE


def test_a_test_with_too_little_usable_area_says_so(tmp_path):
    path = saved(Image.new("RGB", (128, 128)), tmp_path / "black.png")
    with Image.open(path) as image:
        tests = by_name(run_forensics(path, image.convert("RGB"), "png", MediaConfig()))
    assert tests[NOISE_LEVEL].status is CheckStatus.UNAVAILABLE
    assert "too little usable area" in tests[NOISE_LEVEL].reason


def test_a_tiny_image_is_not_examined(tmp_path):
    path = saved(natural_image(size=32), tmp_path / "a.png")
    with Image.open(path) as image:
        check = run_forensics(path, image.convert("RGB"), "png", MediaConfig())
    assert check.status is CheckStatus.UNAVAILABLE
    assert check.tests == []
    assert "64px" in check.limitations[0]


def test_without_opencv_the_check_is_unavailable(tmp_path, monkeypatch):
    path = saved(natural_image(), tmp_path / "a.png")
    monkeypatch.setattr(forensics, "_ensure_libraries", lambda: False)
    with Image.open(path) as image:
        check = run_forensics(path, image.convert("RGB"), "png", MediaConfig())
    assert check.status is CheckStatus.UNAVAILABLE
    assert "OpenCV" in check.limitations[0]


def test_flags_and_regions_follow_the_limit(tmp_path, monkeypatch):
    path = saved(natural_image(), tmp_path / "a.jpg")
    z = _blob_map()
    monkeypatch.setattr(forensics, "FLAG_LIMITS", {ELA: 0.5, NOISE_LEVEL: 0.5})
    monkeypatch.setattr(
        forensics,
        "measure_all",
        lambda rgb: {
            name: Measurement(0.5 if name == ELA else 0.49, z if name in (ELA, NOISE_LEVEL) else None, 16)
            for name in TEST_NAMES
        },
    )
    with Image.open(path) as image:
        tests = by_name(run_forensics(path, image.convert("RGB"), "jpeg", MediaConfig()))
    # At the limit counts as unusual, and only an unusual reading marks regions.
    assert tests[ELA].flagged is True and tests[ELA].regions
    assert tests[NOISE_LEVEL].flagged is False and not tests[NOISE_LEVEL].regions
    # A test with no measured limit isn't called unusual or normal.
    assert tests[NOISE_UNEVENNESS].flagged is None and tests[NOISE_UNEVENNESS].limit is None


def test_a_large_image_is_examined_in_the_middle_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(forensics, "MAX_PIXELS", 256 * 256)
    monkeypatch.setattr(forensics, "FLAG_LIMITS", {ELA: 0.0})
    seen = {}

    def fake_measure(rgb):
        seen["shape"] = rgb.shape
        return {name: Measurement(1.0, _blob_map(), 16) for name in TEST_NAMES}

    monkeypatch.setattr(forensics, "measure_all", fake_measure)
    path = saved(natural_image(size=512), tmp_path / "a.jpg")
    with Image.open(path) as image:
        check = run_forensics(path, image.convert("RGB"), "jpeg", MediaConfig())
    assert seen["shape"][:2] == (256, 256)
    assert any("only the middle" in line for line in check.limitations)
    # The box is reported where it is in the whole image, not in the middle part.
    assert by_name(check)[ELA].regions[0] == ForensicRegion(x=128 + 48, y=128 + 80, width=64, height=64)


def test_a_failure_is_reported_without_saying_anything_about_the_file(tmp_path, monkeypatch, caplog):
    path = saved(natural_image(), tmp_path / "secret-name.png")

    def fail(rgb):
        raise RuntimeError(f"could not read {path}")

    monkeypatch.setattr(forensics, "measure_all", fail)
    with caplog.at_level(logging.WARNING), Image.open(path) as image:
        check = run_forensics(path, image.convert("RGB"), "png", MediaConfig())
    assert check.status is CheckStatus.UNAVAILABLE
    assert "secret-name" not in caplog.text
    assert "secret-name" not in check.model_dump_json()


def test_a_stuck_check_stops_at_the_time_limit(tmp_path, monkeypatch):
    path = saved(natural_image(), tmp_path / "a.png")
    monkeypatch.setattr(forensics, "measure_all", lambda rgb: time.sleep(1.0))
    with Image.open(path) as image:
        rgb = image.convert("RGB")
    started = time.monotonic()
    check = run_forensics(path, rgb, "png", MediaConfig(forensics_time_limit_s=0.05))
    assert time.monotonic() - started < 0.9
    assert check.status is CheckStatus.UNAVAILABLE
    assert "didn't finish" in check.limitations[0]


def test_regions_use_the_upright_image(tmp_path, monkeypatch):
    """The check reads the image already turned upright, so boxes line up with what people see."""
    from backend.media import analyzer

    image = natural_image(size=256).crop((0, 0, 256, 128))
    exif = Image.Exif()
    exif[0x0112] = 6
    path = saved(image, tmp_path / "turned.jpg", exif=exif)
    seen = {}

    def spy(path, picture, container, config):
        seen["size"] = picture.size
        return ForensicsCheck(status=CheckStatus.COMPLETE)

    monkeypatch.setattr(analyzer, "run_forensics", spy)
    analyze_media(path, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert seen["size"] == (128, 256)


# In the analysis.


def _all_flagged(path, image, container, config):
    return ForensicsCheck(
        status=CheckStatus.COMPLETE,
        source_format=container,
        tests=[
            ForensicTest(
                name=name,
                status=CheckStatus.COMPLETE,
                score=9.0,
                limit=1.0,
                flagged=True,
                regions=[ForensicRegion(x=1, y=2, width=3, height=4)],
            )
            for name in TEST_NAMES
        ],
    )


def test_unusual_readings_never_change_the_score_or_assessment(tmp_path, monkeypatch):
    from backend.media import analyzer

    path = saved(natural_image(), tmp_path / "a.png")
    plain = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig())
    monkeypatch.setattr(analyzer, "run_forensics", _all_flagged)
    flagged = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig())
    assert flagged.score == plain.score
    assert flagged.assessment == plain.assessment
    assert flagged.summary == plain.summary
    lines = [line for line in flagged.evidence if "Pixel forensics" in line]
    assert lines == [
        f"Pixel forensics tests read as unusual: {len(TEST_NAMES) - len(forensics.ADDS_NOTHING)}. "
        "Ordinary editing and re-saving can also cause this."
    ]


def test_tests_measured_as_adding_nothing_are_not_offered_as_evidence(tmp_path, monkeypatch):
    from backend.media import analyzer

    monkeypatch.setattr(
        analyzer,
        "run_forensics",
        lambda *args: ForensicsCheck(
            status=CheckStatus.COMPLETE,
            tests=[ForensicTest(name=NOISE_LEVEL, status=CheckStatus.COMPLETE, score=9.0, limit=1.0, flagged=True)],
        ),
    )
    path = saved(natural_image(), tmp_path / "a.png")
    result = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig())
    assert not any("Pixel forensics" in line for line in result.evidence)
    entry = {check["check_id"]: check for check in result.to_checks()}["media.forensics"]
    assert entry["result"] == "1 of 1 tests unusual, 0 of those measured as useful"


def test_no_unusual_readings_add_no_evidence_line(tmp_path, monkeypatch):
    from backend.media import analyzer

    monkeypatch.setattr(
        analyzer,
        "run_forensics",
        lambda *args: ForensicsCheck(
            status=CheckStatus.COMPLETE, tests=[ForensicTest(name=ELA, status=CheckStatus.COMPLETE, flagged=False)]
        ),
    )
    path = saved(natural_image(), tmp_path / "a.png")
    result = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig())
    assert not any("Pixel forensics" in line for line in result.evidence)


def test_a_video_reports_not_applicable_and_why(tmp_path):
    path = write_video(tmp_path / "a.mp4", [((10, 20, 30), 1.0), ((200, 100, 50), 1.0)])
    result = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig())
    assert result.checks.forensics.status is CheckStatus.NOT_APPLICABLE
    entry = {check["check_id"]: check for check in result.to_checks()}["media.forensics"]
    assert entry["status"] == "not_applicable"
    assert "images only" in " ".join(entry["limitations"])


def test_a_rejected_file_still_reports_the_check(tmp_path):
    path = tmp_path / "bad.png"
    path.write_bytes(b"not an image")
    result = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig())
    assert result.checks.forensics.status is CheckStatus.UNAVAILABLE


def test_a_real_analysis_gives_the_check(tmp_path):
    path = saved(natural_image(), tmp_path / "a.jpg")
    result = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig())
    entry = {check["check_id"]: check for check in result.to_checks()}["media.forensics"]
    assert entry["module"] == "media"
    assert entry["status"] == "complete"
    assert entry["benchmark"] is None
    assert len(entry["artifacts"]) == len(TEST_NAMES)
    for artifact in entry["artifacts"]:
        assert all(isinstance(value, str) for value in artifact.values())


# The explanation.


def _entry(check: ForensicsCheck) -> dict:
    return explain_module._forensics(check)


def test_unusual_readings_are_described_as_something_to_look_at(tmp_path):
    entry = _entry(_all_flagged(None, None, "jpeg", None))
    assert entry["result"].startswith(f"{len(TEST_NAMES)} of {len(TEST_NAMES)} tests unusual")
    assert "regions marked" in entry["result"]
    limitations = " ".join(entry["limitations"])
    assert "doesn't show an image is fake" in limitations
    assert "not that the area was edited" in limitations
    assert "does not change the overall score" in limitations


def test_no_unusual_readings_do_not_clear_the_image():
    check = ForensicsCheck(
        status=CheckStatus.COMPLETE, tests=[ForensicTest(name=ELA, status=CheckStatus.COMPLETE, score=0.1, limit=1.0, flagged=False)]
    )
    entry = _entry(check)
    assert entry["result"] == "0 of 1 tests unusual"
    assert "doesn't show the image is genuine" in entry["reasoning"]


def test_regions_and_the_reason_reach_the_artifact():
    check = ForensicsCheck(
        status=CheckStatus.COMPLETE,
        tests=[
            ForensicTest(
                name=ELA,
                status=CheckStatus.COMPLETE,
                score=1.5,
                limit=1.0,
                flagged=True,
                regions=[ForensicRegion(x=1, y=2, width=3, height=4)],
            ),
            ForensicTest(name=COMPRESSION_GHOST, status=CheckStatus.UNAVAILABLE, reason="Because."),
        ],
    )
    first, second = _entry(check)["artifacts"]
    assert first["regions"] == "x 1, y 2, width 3, height 4"
    assert first["unusual"] == "true"
    assert second["reason"] == "Because."
    assert "score" not in second and "unusual" not in second


def test_an_unavailable_check_gives_its_reason():
    entry = _entry(ForensicsCheck(status=CheckStatus.UNAVAILABLE, limitations=["No time."]))
    assert entry["result"] == "Not run"
    assert entry["limitations"] == ["No time."]
    assert entry["artifacts"] == []


FIGURES = {
    "settings": {"target_real_flagged": 0.05},
    "verdicts": {ELA: {"adds_nothing": False}, FREQUENCY_PEAKS: {"adds_nothing": True}},
    "test_split": {
        ELA: {
            "jpeg_files_only": {
                "groups": {"ai_generated": {"auc": 0.65, "flagged": {"count": 5, "total": 23}}, "edited": {"auc": 0.62}},
                "real_flagged": {"count": 9, "total": 134},
            }
        },
        FREQUENCY_PEAKS: {"jpeg_files_only": {"groups": {"ai_generated": {"auc": 0.52}, "edited": {"auc": 0.43}}}},
    },
}


def test_a_test_that_adds_nothing_says_so_plainly():
    sentence = explain_module._forensic_figures_sentence(FREQUENCY_PEAKS, FIGURES)
    assert "added nothing" in sentence
    assert "0.52" in sentence and "0.43" in sentence


def test_a_useful_test_gives_its_figures():
    sentence = explain_module._forensic_figures_sentence(ELA, FIGURES)
    assert "added nothing" not in sentence
    assert "0.65" in sentence
    assert "5 of 23" in sentence and "9 of 134" in sentence


def test_the_splice_result_is_stated_with_the_real_figures():
    limitations = " ".join(_entry(_all_flagged(None, None, "jpeg", None))["limitations"])
    assert "no test reliably told spliced images from unspliced" in limitations


@pytest.mark.parametrize("figures", [None, {}, {"verdicts": {}}])
def test_without_figures_a_test_says_it_was_not_measured(figures):
    assert "not been measured" in explain_module._forensic_figures_sentence(ELA, figures)


def test_figures_for_other_limits_are_not_used(tmp_path, monkeypatch):
    document = tmp_path / "r.json"
    document.write_text(json.dumps({"limits_chosen_on_calibration": {ELA: 123.0}, "verdicts": {}, "test_split": {}}))
    explain_module._read_results.cache_clear()
    assert explain_module.load_forensics_figures(document) is None
    assert explain_module.load_forensics_figures(tmp_path / "missing.json") is None


# The measuring tool.


def test_limit_is_the_score_the_top_share_of_real_images_reach():
    assert evaluation.choose_limit(list(range(100)), 0.05) == 95
    assert evaluation.choose_limit([]) is None


def test_auc_interval_for_clear_and_for_no_separation():
    clear = evaluation.auc_with_interval([5.0, 6.0, 7.0, 8.0] * 10, [1.0, 2.0, 3.0, 4.0] * 10)
    assert clear["auc"] == 1.0 and clear["ci95"][0] == 1.0
    same = evaluation.auc_with_interval([1.0, 2.0, 3.0, 4.0] * 10, [1.0, 2.0, 3.0, 4.0] * 10)
    assert same["auc"] == 0.5
    assert same["ci95"][0] < 0.5 < same["ci95"][1]
    assert evaluation.auc_with_interval([], [1.0])["auc"] is None


@pytest.mark.parametrize(
    "entry, expected",
    [
        ({"auc": 0.7, "ci95": [0.6, 0.8]}, True),
        ({"auc": 0.7, "ci95": [0.45, 0.9]}, False),
        ({"auc": 0.55, "ci95": [0.51, 0.6]}, False),
        ({"auc": 0.2, "ci95": [0.1, 0.3]}, False),
        ({"auc": None, "ci95": None}, False),
    ],
)
def test_what_counts_as_separating(entry, expected):
    assert evaluation.separates(entry) is expected


def _z_at(left: int, top: int, size: int) -> Measurement:
    z = np.zeros((32, 32))
    z[top:top + size, left:left + size] = 9
    return Measurement(1.0, z, 16)


def test_a_region_on_the_patch_counts_as_found():
    assert evaluation._region_hit(_z_at(4, 4, 4), (64, 64, 128, 128))


def test_a_region_elsewhere_does_not_count():
    assert not evaluation._region_hit(_z_at(20, 20, 4), (64, 64, 128, 128))


def test_a_huge_region_that_happens_to_cover_the_patch_does_not_count():
    assert not evaluation._region_hit(_z_at(2, 2, 12), (64, 64, 128, 128))


def test_no_block_map_means_no_region_found():
    assert not evaluation._region_hit(Measurement(1.0), (0, 0, 10, 10))


def _group(value: float, low: float) -> dict:
    return {"auc": value, "ci95": [low, 1.0]}


def _whole(jpeg: float, resaved: float) -> dict:
    return {
        test: {
            "jpeg_files_only": {"groups": {"ai_generated": _group(jpeg, 0.55), "edited": _group(0.5, 0.4)}},
            "all_re_saved_the_same_way": {"groups": {"ai_generated": _group(resaved, 0.55), "edited": _group(0.5, 0.4)}},
        }
        for test in TEST_NAMES
    }


def _splices(value: float) -> dict:
    return {"s": {test: {"against_same_image_without_the_patch": _group(value, 0.55)} for test in TEST_NAMES}}


def test_a_test_must_hold_up_both_ways_or_it_may_only_be_reading_the_file_type():
    verdict = evaluation._verdict(_whole(0.8, 0.5), _splices(0.5))
    assert verdict[ELA]["separates_from_real_whichever_way_measured"] == []
    assert verdict[ELA]["adds_nothing"] is True


def test_a_test_that_holds_up_both_ways_is_kept():
    verdict = evaluation._verdict(_whole(0.8, 0.7), _splices(0.5))
    assert verdict[ELA]["separates_from_real_whichever_way_measured"] == ["ai_generated"]
    assert verdict[ELA]["adds_nothing"] is False


def test_finding_splices_alone_is_enough_to_count():
    verdict = evaluation._verdict(_whole(0.5, 0.5), _splices(0.9))
    assert verdict[ELA]["separates_spliced_from_unspliced"] == ["s"]
    assert verdict[ELA]["adds_nothing"] is False


def test_the_tool_runs_end_to_end_and_writes_no_file_names(tmp_path):
    for label, seeds in (("real", range(1, 9)), ("fake", range(20, 28))):
        folder = tmp_path / label / ("general" if label == "real" else "ai_generated")
        folder.mkdir(parents=True)
        for seed in seeds:
            image = natural_image(seed=seed, size=256)
            saved(image, folder / f"private-name-{seed}.jpg", quality=85)
    out = tmp_path / "out.json"
    code = evaluation.main(
        ["--real", str(tmp_path / "real"), "--fake", str(tmp_path / "fake"), "--out", str(out), "--source", "n|l|u"]
    )
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "private-name" not in text
    assert str(tmp_path) not in text
    document = json.loads(text)
    assert set(document["verdicts"]) == set(TEST_NAMES)
    assert document["beside_the_detector_in_use"] is None


def test_the_tool_refuses_a_missing_folder(tmp_path, capsys):
    code = evaluation.main(
        ["--real", str(tmp_path / "no"), "--fake", str(tmp_path), "--out", str(tmp_path / "o.json"), "--source", "n|l|u"]
    )
    assert code == 2


# The results file.


def test_limits_in_the_code_are_the_ones_measured():
    assert FLAG_LIMITS == json.loads(RESULTS.read_text(encoding="utf-8"))["limits_chosen_on_calibration"]


def test_tests_treated_as_adding_nothing_are_the_ones_measured_so():
    verdicts = json.loads(RESULTS.read_text(encoding="utf-8"))["verdicts"]
    assert forensics.ADDS_NOTHING == {name for name, verdict in verdicts.items() if verdict["adds_nothing"]}


def test_the_explanation_reads_the_measured_figures():
    explain_module._read_results.cache_clear()
    figures = explain_module.load_forensics_figures()
    assert figures is not None
    for name in TEST_NAMES:
        assert "not been measured" not in explain_module._forensic_figures_sentence(name, figures)


def test_the_results_file_holds_no_file_names():
    text = RESULTS.read_text(encoding="utf-8")
    assert "samples_commons" not in text
    assert ".jpg" not in text and ".png" not in text
    assert "C:\\\\" not in text
