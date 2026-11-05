from __future__ import annotations

import sys

import pytest

from backend.media import MediaConfig, analyze_media
from backend.media.classifier import HuggingFaceClassifier, synthetic_class_index
from backend.media.errors import ClassifierUnavailable
from backend.media.models import CheckStatus
from backend.media.tests.helpers import patterned_image


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        ({0: "Real", 1: "Fake"}, 1),
        ({0: "FAKE", 1: "REAL"}, 0),
        ({0: "human", 1: "AI-generated"}, 1),
    ],
)
def test_synthetic_class_is_found_by_name(labels, expected):
    assert synthetic_class_index(labels) == expected


@pytest.mark.parametrize("labels", [{0: "LABEL_0", 1: "LABEL_1"}, {0: "fake", 1: "synthetic"}])
def test_ambiguous_labels_are_refused(labels):
    with pytest.raises(ClassifierUnavailable):
        synthetic_class_index(labels)


def test_missing_model_dependencies_are_reported(image_file, monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    classifier = HuggingFaceClassifier(MediaConfig())
    result = analyze_media(image_file, classifier=classifier, config=MediaConfig())
    assert result.status is CheckStatus.UNAVAILABLE
    assert result.score is None
    assert result.checks.phash.status is CheckStatus.COMPLETE
    assert any("requirements-model.txt" in line for line in result.limitations)


def test_missing_weights_are_reported_without_downloading(image_file):
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    config = MediaConfig(model_id="trustfeed-tests/does-not-exist", model_revision=None)
    result = analyze_media(image_file, classifier=HuggingFaceClassifier(config), config=config)
    assert result.status is CheckStatus.UNAVAILABLE
    assert result.score is None
    assert any("download-model" in line for line in result.limitations)


def _save_tiny_model(path, *, safe: bool = True, labels=None):
    """Save a randomly initialised ViT. Its scores mean nothing; it tests loading."""
    from transformers import ViTConfig, ViTForImageClassification, ViTImageProcessor

    labels = labels or {0: "Real", 1: "Fake"}
    config = ViTConfig(
        image_size=32,
        patch_size=16,
        hidden_size=16,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=16,
        num_labels=2,
        id2label=labels,
        label2id={label: index for index, label in labels.items()},
    )
    ViTForImageClassification(config).save_pretrained(path, safe_serialization=safe)
    ViTImageProcessor(size={"height": 32, "width": 32}).save_pretrained(path)
    return str(path)


def test_real_adapter_runs_on_a_local_safetensors_model(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    config = MediaConfig(model_id=_save_tiny_model(tmp_path / "model"), model_revision=None, device="cpu")
    classifier = HuggingFaceClassifier(config)

    scores = classifier.predict([patterned_image(seed=seed) for seed in range(10)])

    assert len(scores) == 10
    assert all(0 <= score <= 1 for score in scores)
    # A second call reuses the loaded model and gives the same answer.
    assert classifier.predict([patterned_image(seed=0)])[0] == pytest.approx(scores[0], abs=1e-6)


def test_real_adapter_end_to_end(tmp_path, video_file):
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    config = MediaConfig(model_id=_save_tiny_model(tmp_path / "model"), model_revision=None, device="cpu")
    result = analyze_media(video_file, classifier=HuggingFaceClassifier(config), config=config)
    assert result.status is CheckStatus.COMPLETE
    assert result.checks.classifier.items_scored == 2
    assert 0 <= result.score <= 1


def test_pickle_weights_are_refused(tmp_path, image_file):
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    model = _save_tiny_model(tmp_path / "model", safe=False)
    config = MediaConfig(model_id=model, model_revision=None, device="cpu")
    result = analyze_media(image_file, classifier=HuggingFaceClassifier(config), config=config)
    assert result.status is CheckStatus.UNAVAILABLE
    assert result.score is None


def test_model_with_unknown_labels_is_refused(tmp_path, image_file):
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    model = _save_tiny_model(tmp_path / "model", labels={0: "cat", 1: "dog"})
    config = MediaConfig(model_id=model, model_revision=None, device="cpu")
    result = analyze_media(image_file, classifier=HuggingFaceClassifier(config), config=config)
    assert result.status is CheckStatus.UNAVAILABLE
    assert any("synthetic class" in line for line in result.limitations)


def test_invalid_device_is_reported(tmp_path, image_file):
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    config = MediaConfig(model_id=_save_tiny_model(tmp_path / "model"), model_revision=None, device="not-a-device")
    result = analyze_media(image_file, classifier=HuggingFaceClassifier(config), config=config)
    assert result.status is CheckStatus.UNAVAILABLE
    assert any("device" in line for line in result.limitations)
