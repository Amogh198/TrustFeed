"""Explanation checks and the occlusion heatmap. Stand-ins replace the model."""

from __future__ import annotations

import io
import json
from dataclasses import replace

import pytest
from PIL import Image

from backend.media import MediaConfig, analyze_media
from backend.media.__main__ import main as cli
from backend.media.errors import ClassifierUnavailable
from backend.media.explain import BENCHMARK_PATH, build_checks, load_benchmark
from backend.media.heatmap import (
    DISPLAY_FLOOR,
    GRID_SIZE,
    HEATMAP_LABEL,
    OcclusionHeatmap,
    occlusion_heatmap,
    render_overlay,
    render_png,
)
from backend.media.models import CheckStatus
from backend.media.tests.helpers import FakeClassifier, patterned_image, write_video

CONFIG = MediaConfig()
MODEL = CONFIG.model_id
REVISION = CONFIG.model_revision


class PinnedClassifier(FakeClassifier):
    """Reports the benchmarked model's name, to test figures being attached."""

    model_id = MODEL
    model_revision = REVISION


def analyzed(tmp_path, score=0.1, classifier=None):
    path = tmp_path / "a.png"
    patterned_image().save(path)
    return analyze_media(path, classifier=classifier or PinnedClassifier(score), config=CONFIG)


def by_id(checks):
    return {check["check_id"]: check for check in checks}


def results_file(tmp_path, **changes):
    document = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    document.update(changes)
    path = tmp_path / "results.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# Benchmark figures


def test_benchmark_figures_come_from_the_published_test_split():
    document = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    split = next(m for m in document["models"] if m["model_id"] == MODEL)["current_bands"]["test_split"]
    figures = load_benchmark(MODEL, REVISION, CONFIG)
    assert figures["n_fake"] == split["n"]["fake"] == 157
    assert figures["n_real"] == split["n"]["real"] == 75
    assert figures["recall"] == split["recall"]["value"]
    assert figures["recall_ci95"] == split["recall"]["ci95"]
    assert figures["false_positive_rate"] == split["false_positive_rate"]["value"]
    assert figures["fpr_ci95"] == split["false_positive_rate"]["ci95"]
    assert figures["low_fake"] == split["confusion"]["fake"]["low"]
    assert figures["measured_at"] == "2026-11-05"


@pytest.mark.parametrize(
    ("model", "revision", "config"),
    [
        ("other/model", REVISION, CONFIG),
        (MODEL, "another-revision", CONFIG),
        (None, None, CONFIG),
        (MODEL, REVISION, replace(CONFIG, low_score=0.01)),
        (MODEL, REVISION, replace(CONFIG, elevated_score=0.5)),
    ],
)
def test_figures_are_null_unless_measured_for_this_model_and_these_bands(model, revision, config):
    assert load_benchmark(model, revision, config) is None


def test_missing_or_broken_results_mean_unmeasured(tmp_path):
    assert load_benchmark(MODEL, REVISION, CONFIG, tmp_path / "none.json") is None
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_benchmark(MODEL, REVISION, CONFIG, broken) is None
    assert load_benchmark(MODEL, REVISION, CONFIG, results_file(tmp_path, models="wrong")) is None


# Checks


def test_every_check_has_the_agreed_fields(tmp_path):
    fields = {"check_id", "module", "label", "status", "result", "reasoning", "benchmark", "artifacts", "limitations"}
    checks = analyzed(tmp_path).to_checks()
    assert [check["check_id"] for check in checks] == [
        "media.classifier",
        "media.metadata",
        "media.phash",
        "media.keyframes",
    ]
    for check in checks:
        assert set(check) == fields
        assert check["module"] == "media"
        assert check["result"] and check["reasoning"]
    json.dumps(checks)


def test_low_score_is_not_reassuring_and_says_how_often_fakes_score_low(tmp_path):
    check = by_id(build_checks(analyzed(tmp_path, 0.1), config=CONFIG))["media.classifier"]
    assert check["result"] == "0.1000, low band"
    assert "does not show the image is authentic" in check["reasoning"]
    assert "128 of 157 fake images also scored low" in check["reasoning"]
    assert "a low score is weak evidence" in check["reasoning"]
    assert any("did not measure face swaps" in line for line in check["limitations"])
    assert "flags very few fakes: 1 of 157 when measured." in " ".join(check["limitations"])


def test_elevated_score_reports_measured_misses_and_false_flags(tmp_path):
    check = by_id(build_checks(analyzed(tmp_path, 0.9), config=CONFIG))["media.classifier"]
    assert check["result"] == "0.9000, elevated band"
    assert "It is not proof" in check["reasoning"]
    assert "caught 1 of 157 fake images" in check["reasoning"]
    assert "wrongly flagged 1 of 75 real ones" in check["reasoning"]


def test_middle_score_is_inconclusive(tmp_path):
    check = by_id(build_checks(analyzed(tmp_path, 0.5), config=CONFIG))["media.classifier"]
    assert "inconclusive" in check["result"] or "inconclusive" in check["reasoning"]
    assert "does not clearly point either way" in check["reasoning"]


def test_unmeasured_model_has_a_null_benchmark(tmp_path):
    check = by_id(build_checks(analyzed(tmp_path, classifier=FakeClassifier(0.1)), config=CONFIG))["media.classifier"]
    assert check["benchmark"] is None
    assert "of 157" not in check["reasoning"]


def test_unavailable_model_invents_no_figures(tmp_path):
    result = analyzed(tmp_path, classifier=PinnedClassifier(error=ClassifierUnavailable("no weights")))
    check = by_id(build_checks(result, config=CONFIG))["media.classifier"]
    assert check["status"] == "unavailable"
    assert check["result"] == "No model result"
    assert check["benchmark"] is None
    assert "no weights" in " ".join(check["limitations"])


def test_image_figures_are_not_applied_to_video(tmp_path):
    video = write_video(tmp_path / "clip.mp4", [((0, 0, 255), 2.0), ((255, 0, 0), 2.0)])
    result = analyze_media(video, classifier=PinnedClassifier(0.1), config=CONFIG)
    checks = by_id(build_checks(result, config=CONFIG))
    assert checks["media.classifier"]["benchmark"] is None
    assert "on video has not been measured" in checks["media.classifier"]["reasoning"]
    assert checks["media.keyframes"]["status"] == "complete"
    assert checks["media.keyframes"]["result"].startswith("2 keyframes")
    assert checks["media.metadata"]["result"].count("seconds") == 1


def test_image_has_no_keyframes(tmp_path):
    check = by_id(build_checks(analyzed(tmp_path), config=CONFIG))["media.keyframes"]
    assert check["status"] == "not_applicable"


def test_rejected_media_explains_that_nothing_ran(tmp_path):
    path = tmp_path / "bad.png"
    path.write_bytes(b"not an image")
    for check in build_checks(analyze_media(path, classifier=PinnedClassifier(), config=CONFIG), config=CONFIG):
        assert check["status"] == "unavailable"
        assert check["benchmark"] is None


def test_metadata_check_never_exposes_gps_values(tmp_path):
    result = analyzed(tmp_path)
    result.checks.metadata.has_gps = True
    result.checks.metadata.fields["GPSInfo"] = "12.97,77.59"
    check = by_id(build_checks(result, config=CONFIG))["media.metadata"]
    assert "GPS data present, not shown" in check["result"]
    assert "12.97" not in json.dumps(check)


def test_metadata_says_it_can_be_false(tmp_path):
    check = by_id(build_checks(analyzed(tmp_path), config=CONFIG))["media.metadata"]
    assert any("can be missing, removed or false" in line for line in check["limitations"])


def test_generator_hint_is_explained(tmp_path):
    result = analyzed(tmp_path)
    result.checks.metadata.generator_hint = True
    result.checks.metadata.indicators = ["Software tag names a generator."]
    check = by_id(build_checks(result, config=CONFIG))["media.metadata"]
    assert "names a generator or editing tool" in check["reasoning"]
    assert "Software tag names a generator." in check["reasoning"]


def test_empty_reference_comparison_is_not_called_evidence(tmp_path):
    check = by_id(build_checks(analyzed(tmp_path), config=CONFIG))["media.phash"]
    assert check["result"] == "Not compared"
    assert "found nothing either way" in check["reasoning"]


def test_heatmap_link_is_attached_only_when_given(tmp_path):
    result = analyzed(tmp_path)
    assert by_id(result.to_checks())["media.classifier"]["artifacts"] == []
    checks = by_id(result.to_checks(heatmap_url="/api/cases/x/artifacts/y.png"))
    assert checks["media.classifier"]["artifacts"] == [{"kind": "occlusion_heatmap", "url": "/api/cases/x/artifacts/y.png"}]


# Heatmap


class CornerClassifier(FakeClassifier):
    """Scores high only while the red square in the top-left area is visible."""

    def predict(self, images):
        self.seen += len(images)
        return [0.9 if image.getpixel((16, 16))[:3] == (255, 0, 0) else 0.1 for image in images]


def red_corner_image(size=256):
    image = Image.new("RGB", (size, size), "white")
    image.paste((255, 0, 0), (0, 0, size // GRID_SIZE, size // GRID_SIZE))
    return image


def test_heatmap_finds_the_area_that_moves_the_score():
    result = occlusion_heatmap(red_corner_image(), CornerClassifier())
    assert result.status is CheckStatus.COMPLETE
    assert result.base_score == 0.9
    assert result.changes[0][0] == 0.8
    assert result.max_change == 0.8
    assert result.notable is True
    assert all(value == 0 for r, row in enumerate(result.changes) for c, value in enumerate(row) if (r, c) != (0, 0))
    assert result.label == HEATMAP_LABEL
    assert "not proof of editing" in result.label


def test_rows_and_columns_are_not_swapped():
    image = Image.new("RGB", (256, 256), "white")
    image.paste((255, 0, 0), (96, 0, 128, 32))

    class Marked(FakeClassifier):
        def predict(self, images):
            return [0.9 if picture.getpixel((112, 16))[:3] == (255, 0, 0) else 0.1 for picture in images]

    result = occlusion_heatmap(image, Marked())
    assert result.changes[0][3] == 0.8
    assert result.changes[3][0] == 0


def test_heatmap_says_its_starting_score_can_differ():
    assert "starting score can differ" in " ".join(occlusion_heatmap(red_corner_image(), CornerClassifier()).limitations)


def test_heatmap_runs_each_area_once_in_batches():
    classifier = CornerClassifier()
    occlusion_heatmap(red_corner_image(), classifier, batch_size=5)
    assert classifier.seen == GRID_SIZE**2 + 1


def test_area_that_lowers_the_score_is_negative():
    class Opposite(FakeClassifier):
        def predict(self, images):
            return [0.1 if image.getpixel((16, 16))[:3] == (255, 0, 0) else 0.9 for image in images]

    result = occlusion_heatmap(red_corner_image(), Opposite())
    assert result.changes[0][0] == -0.8
    assert result.max_change == 0.8


def test_small_changes_are_reported_as_nothing_standing_out():
    class Quiet(FakeClassifier):
        def predict(self, images):
            return [0.001 if image.getpixel((16, 16))[:3] == (255, 0, 0) else 0.0005 for image in images]

    result = occlusion_heatmap(red_corner_image(), Quiet())
    assert result.status is CheckStatus.COMPLETE
    assert result.notable is False
    assert "No area stands out" in result.reasoning


def test_covering_does_not_change_the_callers_image():
    image = red_corner_image()
    before = image.tobytes()
    occlusion_heatmap(image, CornerClassifier())
    assert image.tobytes() == before


@pytest.mark.parametrize(
    ("classifier", "reason"),
    [
        (FakeClassifier(error=ClassifierUnavailable("no weights")), "no weights"),
        (FakeClassifier(error=RuntimeError("private detail")), "failed unexpectedly"),
        (FakeClassifier(score=float("nan")), "invalid output"),
        (FakeClassifier(score=1.5), "invalid output"),
        (FakeClassifier(score=[]), "invalid output"),
    ],
)
def test_failure_is_reported_without_a_picture(classifier, reason, caplog):
    result = occlusion_heatmap(red_corner_image(), classifier)
    assert result.status is CheckStatus.UNAVAILABLE
    assert result.changes is None
    assert result.base_score is None
    assert reason in result.reasoning
    assert "private detail" not in caplog.text
    with pytest.raises(ValueError, match="no measurements"):
        render_png(result)


def test_running_out_of_time_gives_no_partial_picture():
    result = occlusion_heatmap(red_corner_image(), CornerClassifier(), max_seconds=-1)
    assert result.status is CheckStatus.UNAVAILABLE
    assert result.changes is None
    assert "did not finish" in result.reasoning


def test_tiny_image_is_refused():
    classifier = CornerClassifier()
    result = occlusion_heatmap(red_corner_image(32), classifier)
    assert result.status is CheckStatus.UNAVAILABLE
    assert classifier.seen == 0


def test_large_image_is_scaled_before_covering():
    sizes = []

    class Recording(FakeClassifier):
        def predict(self, images):
            sizes.extend(image.size for image in images)
            return [0.5] * len(images)

    occlusion_heatmap(red_corner_image(2000), Recording())
    assert set(sizes) == {(512, 512)}


def picture_of(changes):
    largest = max(abs(value) for row in changes for value in row)
    return OcclusionHeatmap(status=CheckStatus.COMPLETE, changes=changes, max_change=largest, reasoning="x")


def grid_with(value):
    changes = [[0.0] * GRID_SIZE for _ in range(GRID_SIZE)]
    changes[0][0] = value
    return changes


def test_png_uses_red_for_raising_and_blue_for_lowering():
    raised = Image.open(io.BytesIO(render_png(picture_of(grid_with(0.8))))).convert("RGBA")
    lowered = Image.open(io.BytesIO(render_png(picture_of(grid_with(-0.8))))).convert("RGBA")
    assert raised.getpixel((1, 1))[0] > raised.getpixel((1, 1))[2]
    assert lowered.getpixel((1, 1))[2] > lowered.getpixel((1, 1))[0]
    assert raised.getpixel((100, 100))[3] == 0


def test_tiny_changes_stay_faint_instead_of_being_stretched():
    tiny = Image.open(io.BytesIO(render_png(picture_of(grid_with(DISPLAY_FLOOR / 10))))).convert("RGBA")
    strong = Image.open(io.BytesIO(render_png(picture_of(grid_with(0.8))))).convert("RGBA")
    assert tiny.getpixel((1, 1))[3] < strong.getpixel((1, 1))[3] / 5


def test_stored_png_holds_none_of_the_uploads_pixels():
    data = render_png(occlusion_heatmap(red_corner_image(), CornerClassifier()))
    picture = Image.open(io.BytesIO(data)).convert("RGBA")
    assert picture.size == (GRID_SIZE * 32, GRID_SIZE * 32)
    colours = {colour for _, colour in picture.getcolors(maxcolors=10)}
    assert colours <= {(214, 40, 40, 170), (31, 95, 200, 0)}


def test_overlay_keeps_the_image_and_adds_a_caption():
    image = red_corner_image()
    overlay = Image.open(io.BytesIO(render_overlay(image, occlusion_heatmap(image, CornerClassifier()))))
    assert overlay.width == 256
    assert overlay.height == 256 + 34


# Command line


def test_cli_refuses_to_save_inside_the_repository(tmp_path, capsys):
    source = tmp_path / "a.png"
    patterned_image().save(source)
    inside = BENCHMARK_PATH.parent / "should-not-exist.png"
    assert cli(["heatmap", str(source), "--out", str(inside)]) == 2
    assert not inside.exists()
    assert "outside the repository" in capsys.readouterr().err


def test_cli_writes_the_picture(tmp_path, monkeypatch, capsys):
    from backend.media import __main__ as module

    monkeypatch.setattr(module, "default_classifier", lambda config: CornerClassifier())
    source = tmp_path / "a.png"
    red_corner_image().save(source)
    out = tmp_path / "heat.png"
    assert cli(["heatmap", str(source), "--out", str(out)]) == 0
    assert out.read_bytes().startswith(b"\x89PNG")
    assert '"changes"' not in capsys.readouterr().out
