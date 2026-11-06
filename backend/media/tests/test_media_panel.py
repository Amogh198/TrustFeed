"""The detector panel, the detector comparison and the Nonescape adapter. Stand-ins replace the models."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from backend.media import MediaConfig, analyze_media
from backend.media.errors import ClassifierUnavailable
from backend.media.eval.__main__ import main as eval_cli
from backend.media.eval.compare import (
    auc_with_interval,
    best_combination,
    compare_models,
    contrasts,
    cut_for_false_alarm_rate,
    difference_from_baseline,
    Row,
)
from backend.media.eval.metrics import FAKE, REAL, Scored
from backend.media.eval.runner import run_benchmark
from backend.media.explain import BENCHMARK_PATH, build_checks, load_comparison
from backend.media.models import Assessment, CheckStatus, ModelBand
from backend.media.nonescape import NONESCAPE_MODEL_ID, NonescapeMiniClassifier, download_nonescape
from backend.media.panel import PANEL_MODELS, build_classifier, download_panel
from backend.media.tests.helpers import FakeClassifier, patterned_image, write_video

CONFIG = MediaConfig()
MODEL = CONFIG.model_id
REVISION = CONFIG.model_revision


class InUse(FakeClassifier):
    model_id = MODEL
    model_revision = REVISION


def factory_with(scores: dict[str, float], errors: dict[str, Exception] | None = None, seen: list | None = None):
    def build(config: MediaConfig) -> FakeClassifier:
        if seen is not None:
            seen.append(config.model_id)
        classifier = FakeClassifier(scores.get(config.model_id, 0.5), (errors or {}).get(config.model_id))
        classifier.model_id = config.model_id
        classifier.model_revision = config.model_revision
        return classifier

    return build


def image_file(tmp_path, size=256):
    path = tmp_path / "a.png"
    patterned_image(size=size).save(path)
    return path


def panel_of(result):
    return result.checks.detector_panel


# When it runs


def test_panel_does_not_run_unless_requested(tmp_path):
    seen = []
    result = analyze_media(
        image_file(tmp_path), classifier=InUse(0.1), config=CONFIG, panel_factory=factory_with({}, seen=seen)
    )
    assert panel_of(result) is None
    assert seen == []
    assert "media.detector_panel" not in {check["check_id"] for check in build_checks(result, config=CONFIG)}


def test_every_detector_gives_its_own_result(tmp_path):
    scores = {model_id: 0.3 + index / 20 for index, (model_id, _) in enumerate(PANEL_MODELS)}
    result = analyze_media(
        image_file(tmp_path), classifier=InUse(0.1), config=CONFIG, run_panel=True, panel_factory=factory_with(scores)
    )
    detectors = panel_of(result).detectors
    assert [(d.model_id, d.model_revision) for d in detectors] == list(PANEL_MODELS)
    assert detectors[0].score == 0.1
    assert [d.score for d in detectors[1:]] == [round(scores[model_id], 4) for model_id, _ in PANEL_MODELS[1:]]


def test_detector_in_use_is_not_run_twice(tmp_path):
    seen = []
    in_use = InUse(0.1)
    analyze_media(
        image_file(tmp_path), classifier=in_use, config=CONFIG, run_panel=True, panel_factory=factory_with({}, seen=seen)
    )
    assert in_use.seen == 1
    assert MODEL not in seen
    assert len(seen) == len(PANEL_MODELS) - 1


# It must not change the overall result


@pytest.mark.parametrize("score", [0.1, 0.5, 0.9])
def test_panel_never_changes_the_overall_result(tmp_path, score):
    alarming = {model_id: 0.99 for model_id, _ in PANEL_MODELS}
    without = analyze_media(image_file(tmp_path), classifier=InUse(score), config=CONFIG)
    with_panel = analyze_media(
        image_file(tmp_path), classifier=InUse(score), config=CONFIG, run_panel=True, panel_factory=factory_with(alarming)
    )
    assert with_panel.score == without.score
    assert with_panel.assessment is without.assessment
    assert with_panel.summary == without.summary
    assert with_panel.evidence == without.evidence
    assert with_panel.to_module_result() == without.to_module_result()
    assert with_panel.checks.classifier == without.checks.classifier


def test_low_in_use_score_stays_no_strong_signals_when_others_are_alarmed(tmp_path):
    alarming = {model_id: 0.99 for model_id, _ in PANEL_MODELS}
    result = analyze_media(
        image_file(tmp_path), classifier=InUse(0.1), config=CONFIG, run_panel=True, panel_factory=factory_with(alarming)
    )
    assert result.assessment is Assessment.NO_STRONG_SIGNALS
    assert [d.counted for d in panel_of(result).detectors] == [True] + [False] * (len(PANEL_MODELS) - 1)


# Failures


def test_one_missing_model_does_not_stop_the_others(tmp_path):
    broken = PANEL_MODELS[1][0]
    errors = {broken: ClassifierUnavailable("Model weights are not available locally.")}
    result = analyze_media(
        image_file(tmp_path), classifier=InUse(0.1), config=CONFIG, run_panel=True, panel_factory=factory_with({}, errors)
    )
    by_id = {d.model_id: d for d in panel_of(result).detectors}
    assert by_id[broken].status is CheckStatus.UNAVAILABLE
    assert by_id[broken].score is None
    assert "not available locally" in by_id[broken].limitations[0]
    assert by_id[PANEL_MODELS[2][0]].status is CheckStatus.COMPLETE
    assert panel_of(result).status is CheckStatus.COMPLETE


def test_factory_failure_is_reported_for_that_detector(tmp_path):
    def build(config):
        raise OSError("private path")

    result = analyze_media(image_file(tmp_path), classifier=InUse(0.1), config=CONFIG, run_panel=True, panel_factory=build)
    detector = panel_of(result).detectors[1]
    assert detector.status is CheckStatus.UNAVAILABLE
    assert "private path" not in " ".join(detector.limitations)


def test_panel_is_unavailable_when_nothing_ran(tmp_path):
    missing = ClassifierUnavailable("no weights")
    errors = {model_id: missing for model_id, _ in PANEL_MODELS}
    result = analyze_media(
        image_file(tmp_path),
        classifier=InUse(error=missing),
        config=CONFIG,
        run_panel=True,
        panel_factory=factory_with({}, errors),
    )
    assert panel_of(result).status is CheckStatus.UNAVAILABLE
    check = {c["check_id"]: c for c in build_checks(result, config=CONFIG)}["media.detector_panel"]
    assert check["status"] == "unavailable"
    assert check["result"].startswith("0 of 6 detectors ran")


def test_time_limit_stops_further_detectors_and_says_so(tmp_path):
    seen = []
    config = replace(CONFIG, panel_time_budget_s=0.0)
    result = analyze_media(
        image_file(tmp_path), classifier=InUse(0.1), config=config, run_panel=True, panel_factory=factory_with({}, seen=seen)
    )
    assert seen == []
    later = panel_of(result).detectors[1:]
    assert all(d.status is CheckStatus.UNAVAILABLE for d in later)
    assert all("limit was reached" in d.limitations[0] for d in later)
    assert panel_of(result).detectors[0].score == 0.1


def test_small_image_band_is_inconclusive_on_every_detector(tmp_path):
    alarming = {model_id: 0.99 for model_id, _ in PANEL_MODELS}
    result = analyze_media(
        image_file(tmp_path, size=64),
        classifier=InUse(0.99),
        config=CONFIG,
        run_panel=True,
        panel_factory=factory_with(alarming),
    )
    assert all(d.band is ModelBand.INCONCLUSIVE for d in panel_of(result).detectors)


def test_video_scores_each_detector_across_keyframes(tmp_path):
    video = write_video(tmp_path / "clip.mp4", [((0, 0, 255), 2.0), ((255, 0, 0), 2.0)])
    result = analyze_media(video, classifier=InUse(0.1), config=CONFIG, run_panel=True, panel_factory=factory_with({}))
    assert panel_of(result).detectors[1].status is CheckStatus.COMPLETE
    check = {c["check_id"]: c for c in build_checks(result, config=CONFIG)}["media.detector_panel"]
    assert "Accuracy on video has not been measured" in check["reasoning"]


# Explanation check


def explained(tmp_path, scores=None, score=0.1):
    result = analyze_media(
        image_file(tmp_path), classifier=InUse(score), config=CONFIG, run_panel=True, panel_factory=factory_with(scores or {})
    )
    return {c["check_id"]: c for c in build_checks(result, config=CONFIG)}["media.detector_panel"]


def test_panel_check_has_the_agreed_fields_and_string_artifacts(tmp_path):
    check = explained(tmp_path)
    assert set(check) == {
        "check_id",
        "module",
        "label",
        "status",
        "result",
        "reasoning",
        "benchmark",
        "artifacts",
        "limitations",
    }
    assert check["module"] == "media"
    # The dashboard reads this field as one model's figures, so it must stay empty here.
    assert check["benchmark"] is None
    assert len(check["artifacts"]) == len(PANEL_MODELS)
    for artifact in check["artifacts"]:
        assert artifact["kind"] == "detector_result"
        assert all(isinstance(value, str) for value in artifact.values())
    json.dumps(check)


def test_unknown_score_is_left_out_rather_than_invented(tmp_path):
    errors = {PANEL_MODELS[1][0]: ClassifierUnavailable("no weights")}
    result = analyze_media(
        image_file(tmp_path), classifier=InUse(0.1), config=CONFIG, run_panel=True, panel_factory=factory_with({}, errors)
    )
    check = {c["check_id"]: c for c in build_checks(result, config=CONFIG)}["media.detector_panel"]
    assert "score" not in check["artifacts"][1]
    assert check["artifacts"][1]["status"] == "unavailable"
    assert "no result" in check["reasoning"]


def test_disagreement_is_said_plainly(tmp_path):
    check = explained(tmp_path, {PANEL_MODELS[1][0]: 0.99})
    assert "They disagree on this media" in check["reasoning"]
    assert "1 elevated" in check["result"]


def test_panel_check_says_only_one_detector_counts_and_that_scores_are_not_proof(tmp_path):
    check = explained(tmp_path)
    limitations = " ".join(check["limitations"])
    assert "Only the detector in use affects the overall result." in limitations
    assert "not proof" in limitations
    assert check["artifacts"][0]["counted"] == "true"
    assert all(artifact["counted"] == "false" for artifact in check["artifacts"][1:])
    assert all(artifact["why"].startswith("Shown, not counted") for artifact in check["artifacts"][1:])


def test_measured_figures_in_the_panel_come_from_the_results_file(tmp_path):
    models, baseline_auc = load_comparison()
    check = explained(tmp_path)
    document = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    baseline = next(m for m in document["comparison"]["models"] if m["model"] == document["comparison"]["baseline"])
    assert baseline_auc == baseline["test_split"]["auc"]
    for artifact in check["artifacts"][1:]:
        entry = models[f"{artifact['model_id']}@{artifact['model_revision']}"]
        assert f"AUC {entry['test_split']['auc']:.2f}" in artifact["why"]


def test_missing_or_broken_comparison_means_unmeasured(tmp_path):
    assert load_comparison(tmp_path / "none.json") == ({}, None)
    broken = tmp_path / "broken.json"
    broken.write_text('{"comparison": {"models": "wrong"}}', encoding="utf-8")
    assert load_comparison(broken) == ({}, None)


# Comparison measures


def scored(pairs):
    return [Scored(label, score, "", "c") for label, score in pairs]


PERFECT = scored([(FAKE, 0.9 - i / 100) for i in range(40)] + [(REAL, 0.1 + i / 100) for i in range(40)])
BACKWARDS = scored([(FAKE, 0.1 + i / 100) for i in range(40)] + [(REAL, 0.9 - i / 100) for i in range(40)])


def test_auc_interval_is_repeatable_and_contains_the_estimate():
    first = auc_with_interval(PERFECT, seed=3, samples=50)
    assert first == auc_with_interval(PERFECT, seed=3, samples=50)
    assert first["ci95"][0] <= first["auc"] <= first["ci95"][1]


def test_clear_gain_adds_value_and_no_gain_does_not():
    assert difference_from_baseline(PERFECT, BACKWARDS, samples=50)["adds_value"] is True
    same = difference_from_baseline(PERFECT, PERFECT, samples=50)
    assert same["difference"] == 0
    assert same["adds_value"] is False
    assert difference_from_baseline(BACKWARDS, PERFECT, samples=50)["adds_value"] is False


def test_one_class_gives_no_auc_or_gain():
    only_fake = scored([(FAKE, 0.5)] * 5)
    assert auc_with_interval(only_fake, samples=5) == {"auc": None, "ci95": None}
    assert difference_from_baseline(only_fake, only_fake, samples=5)["adds_value"] is False


def test_false_alarm_cut_flags_no_more_than_the_target_on_calibration():
    items = scored([(REAL, i / 100) for i in range(100)] + [(FAKE, 0.5)] * 10)
    cut = cut_for_false_alarm_rate(items, 0.05)
    assert sum(item.score >= cut for item in items if item.label == REAL) <= 5
    assert sum(item.score >= cut for item in items if item.label == REAL) >= 4


def test_false_alarm_cut_needs_enough_real_images():
    assert cut_for_false_alarm_rate(scored([(REAL, 0.5)] * 10)) is None


def test_contrasts_measure_each_pair_and_mark_small_groups():
    items = [
        Scored(FAKE, 0.9, "", "ai"),
        Scored(REAL, 0.1, "", "people"),
        Scored(REAL, 0.95, "", "general"),
    ]
    result = contrasts(items)
    assert result["ai vs people"]["auc"] == 1.0
    assert result["ai vs general"]["auc"] == 0.0
    assert result["ai vs people"]["too_few_to_conclude"] is True


def rows(split, count, good, bad_seed=0):
    """Column 0 separates the classes and column 1 doesn't."""
    result = []
    for i in range(count):
        noise = ((i * 7 + bad_seed) % count) / count
        result.append(Row(FAKE, "f", split, (0.6 + i / (count * 3) if good else noise, noise, noise)))
        result.append(Row(REAL, "r", split, (0.3 - i / (count * 3) if good else noise, noise, noise)))
    return result


def test_combination_is_chosen_on_calibration_and_measured_on_test():
    # On test images, the column that looked useful on calibration images is noise.
    data = rows("calibration", 30, good=True) + rows("test", 30, good=False)
    result = best_combination(data, ["a", "b", "c"], 1)
    assert result["chosen_on"] == "calibration split"
    assert "a" in result["members"]
    assert result["calibration_auc"] > 0.8
    assert result["test_split"]["auc"] < 0.75


def test_compare_marks_the_baseline_and_uses_only_shared_images():
    def entries(score_of, count=40):
        data = {}
        for i in range(count):
            split = "calibration" if i % 2 else "test"
            data[f"f{i}"] = (FAKE, "ai", split, score_of(i, True))
            data[f"r{i}"] = (REAL, "people", split, score_of(i, False))
        return data

    better = entries(lambda i, fake: (0.8 if fake else 0.2) + i / 1000)
    weak = entries(lambda i, fake: 0.5 + ((i * 7) % 40) / 1000)
    del weak["f0"]
    result = compare_models({"weak@1": weak, "better@2": better}, "weak@1", seconds_per_image={"better@2": 0.5})
    assert result["images_scored_by_every_model"] == 79
    by_name = {model["model"]: model for model in result["models"]}
    assert by_name["weak@1"]["difference_from_baseline"] is None
    assert by_name["better@2"]["difference_from_baseline"]["adds_value"] is True
    assert by_name["better@2"]["seconds_per_image"] == 0.5
    assert "ai vs people" in by_name["better@2"]["contrasts_on_test_split"]


# Benchmark runner


SOURCE = {"name": "test", "licence": "CC0", "url": ""}


def folders(tmp_path):
    real, fake = tmp_path / "real", tmp_path / "fake"
    for folder, seeds in ((real, range(1, 5)), (fake, range(5, 9))):
        folder.mkdir()
        for seed in seeds:
            patterned_image(seed).save(folder / f"{seed}.png")
    return real, fake


def test_benchmark_compares_models_and_holds_no_file_names(tmp_path):
    real, fake = folders(tmp_path)
    result = run_benchmark(
        real,
        fake,
        sources=[SOURCE],
        models=[(MODEL, REVISION), ("other/model", "b" * 40)],
        classifier_factory=factory_with({}),
    )
    assert result["comparison"]["baseline"] == f"{MODEL}@{REVISION}"
    assert result["comparison"]["images_scored_by_every_model"] == 8
    text = json.dumps(result)
    assert ".png" not in text
    assert str(tmp_path).replace("\\", "\\\\") not in text


def test_benchmark_with_one_model_has_no_comparison(tmp_path):
    real, fake = folders(tmp_path)
    result = run_benchmark(real, fake, sources=[SOURCE], classifier_factory=factory_with({}))
    assert result["comparison"] is None


def test_unavailable_model_is_left_out_of_the_comparison(tmp_path):
    real, fake = folders(tmp_path)
    result = run_benchmark(
        real,
        fake,
        sources=[SOURCE],
        models=[(MODEL, REVISION), ("other/model", "b" * 40)],
        classifier_factory=factory_with({}, {"other/model": ClassifierUnavailable("no weights")}),
    )
    assert result["models"][1]["status"] == "unavailable"
    assert result["comparison"] is None


def test_cache_resumes_without_scoring_again_and_gives_the_same_figures(tmp_path):
    real, fake = folders(tmp_path)
    cache = tmp_path / "cache"
    built = []

    def factory(config):
        classifier = FakeClassifier(0.4)
        built.append(classifier)
        return classifier

    first = run_benchmark(real, fake, sources=[SOURCE], classifier_factory=factory, scores_cache=cache)
    second = run_benchmark(real, fake, sources=[SOURCE], classifier_factory=factory, scores_cache=cache)
    assert built[0].seen == 8
    assert built[1].seen == 0
    assert first["models"] == second["models"]


def test_cache_is_separate_for_each_model_revision_and_band(tmp_path):
    real, fake = folders(tmp_path)
    cache = tmp_path / "cache"
    for revision, score in (("a" * 40, 0.1), ("b" * 40, 0.9)):
        result = run_benchmark(
            real,
            fake,
            sources=[SOURCE],
            models=[(MODEL, revision)],
            classifier_factory=lambda config, s=score: FakeClassifier(s),
            scores_cache=cache,
        )
        assert result["models"][0]["current_bands"]["all_images"]["score_histogram"][FAKE][int(score * 10)] == 4


def test_cli_refuses_a_scores_cache_inside_the_repository(tmp_path, capsys):
    real, fake = folders(tmp_path)
    inside = BENCHMARK_PATH.parent / "should-not-exist"
    code = eval_cli(
        ["--real", str(real), "--fake", str(fake), "--out", str(tmp_path / "o.json"), "--source", "a|b|c"]
        + ["--scores-cache", str(inside)],
        classifier_factory=factory_with({}),
    )
    assert code == 2
    assert "outside the repository" in capsys.readouterr().err
    assert not inside.exists()


def test_cli_panel_measures_every_detector(tmp_path):
    real, fake = folders(tmp_path)
    out = tmp_path / "o.json"
    code = eval_cli(
        ["--real", str(real), "--fake", str(fake), "--out", str(out), "--source", "a|b|c", "--panel"],
        classifier_factory=factory_with({}),
    )
    assert code == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert [(m["model_id"], m["model_revision"]) for m in document["models"]] == list(PANEL_MODELS)


# Roster


def test_every_panel_model_is_pinned_and_unique():
    assert len({model_id for model_id, _ in PANEL_MODELS}) == len(PANEL_MODELS)
    for model_id, revision in PANEL_MODELS:
        assert len(revision) == (64 if model_id == NONESCAPE_MODEL_ID else 40)
        int(revision, 16)


def test_build_classifier_never_loads_weights():
    classifier = build_classifier(replace(CONFIG, model_id=NONESCAPE_MODEL_ID, device="cpu"))
    assert isinstance(classifier, NonescapeMiniClassifier)
    assert classifier._loaded is None
    other = build_classifier(CONFIG)
    assert other.model_id == MODEL
    assert other._loaded is None


def test_download_panel_uses_each_pin(monkeypatch):
    calls = []
    monkeypatch.setattr("backend.media.panel.download_model", lambda c: calls.append((c.model_id, c.model_revision)) or "x")
    monkeypatch.setattr("backend.media.panel.download_nonescape", lambda: "y")
    assert download_panel(CONFIG) == ["y"] + ["x"] * (len(PANEL_MODELS) - 1)
    assert calls == [pin for pin in PANEL_MODELS if pin[0] != NONESCAPE_MODEL_ID]


# Nonescape


def tiny_weights(path):
    import torch
    from safetensors.torch import save_file
    from torch import nn
    from torchvision.models import efficientnet_v2_s

    class Mini(nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = efficientnet_v2_s(weights=None, num_classes=1024, dropout=0.2)
            self.head = nn.Linear(1024, 2)

    torch.manual_seed(0)
    save_file(Mini().state_dict(), path)
    return path


def _sha(path):
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_missing_dependencies_are_reported_without_a_crash(tmp_path, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "torchvision.models", None)
    classifier = NonescapeMiniClassifier(tmp_path / "none.safetensors", device="cpu")
    with pytest.raises(ClassifierUnavailable, match="dependencies are not installed"):
        classifier.predict([patterned_image()])


def test_missing_weights_are_reported_with_the_fix(tmp_path):
    pytest.importorskip("torchvision")
    classifier = NonescapeMiniClassifier(tmp_path / "none.safetensors", device="cpu")
    with pytest.raises(ClassifierUnavailable, match="download-model"):
        classifier.predict([patterned_image()])


def test_missing_weights_download_only_when_allowed(tmp_path, monkeypatch):
    pytest.importorskip("torchvision")
    calls = []
    monkeypatch.setattr("backend.media.nonescape.download_nonescape", lambda path: calls.append(path))
    target = tmp_path / "none.safetensors"
    with pytest.raises(ClassifierUnavailable):
        NonescapeMiniClassifier(target, device="cpu").predict([patterned_image()])
    assert calls == []
    with pytest.raises(ClassifierUnavailable):
        NonescapeMiniClassifier(target, device="cpu", allow_download=True).predict([patterned_image()])
    assert calls == [target]


def test_weights_that_do_not_match_the_pin_are_refused_before_loading(tmp_path, monkeypatch):
    pytest.importorskip("torchvision")
    path = tmp_path / "w.safetensors"
    path.write_bytes(b"not the weights")

    def fail(*args, **kwargs):
        raise AssertionError("must not load unverified weights")

    monkeypatch.setattr("safetensors.torch.load_file", fail)
    with pytest.raises(ClassifierUnavailable, match="do not match"):
        NonescapeMiniClassifier(path, device="cpu").predict([patterned_image()])


def test_scores_come_from_the_synthetic_class(tmp_path):
    pytest.importorskip("torchvision")
    import torch

    path = tiny_weights(tmp_path / "w.safetensors")
    classifier = NonescapeMiniClassifier(path, device="cpu")
    classifier.model_revision = _sha(path)
    images = [patterned_image(1), patterned_image(2).convert("RGBA"), patterned_image(3)]
    scores = classifier.predict(images)
    assert len(scores) == 3
    assert all(0 <= score <= 1 for score in scores)

    # Put all weight on the synthetic class, which the upstream examples read from index 1.
    model, _, _ = classifier._loaded
    with torch.no_grad():
        model.head.weight.zero_()
        model.head.bias.copy_(torch.tensor([-50.0, 50.0]))
    assert classifier.predict(images[:1])[0] == pytest.approx(1.0)


def test_download_keeps_only_a_file_matching_the_pin(tmp_path, monkeypatch):
    payload = b"weights"
    import hashlib
    import io

    expected = hashlib.sha256(payload).hexdigest()

    class Response(io.BytesIO):
        pass

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(payload))
    target = tmp_path / "sub" / "w.safetensors"
    assert download_nonescape(target, expected=expected) == target
    assert target.read_bytes() == payload

    other = tmp_path / "other.safetensors"
    with pytest.raises(ValueError, match="do not match"):
        download_nonescape(other, expected="0" * 64)
    assert not other.exists()
    assert not other.with_name(other.name + ".part").exists()
