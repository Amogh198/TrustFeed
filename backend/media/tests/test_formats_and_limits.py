from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from backend.media import MediaConfig, analyze_media
from backend.media.classifier import HuggingFaceClassifier
from backend.media.errors import ClassifierUnavailable
from backend.media.models import CheckStatus, MediaType
from backend.media.phash import JsonHashIndex, ReferenceEntry
from backend.media.tests.helpers import FakeClassifier, patterned_image


@pytest.mark.parametrize(("name", "pillow_format"), [("a.jpg", "JPEG"), ("a.png", "PNG"), ("a.webp", "WEBP")])
def test_supported_image_formats(tmp_path, name, pillow_format):
    path = tmp_path / name
    patterned_image().save(path, format=pillow_format)
    result = analyze_media(path, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert result.failure_code is None
    assert result.media_type is MediaType.IMAGE
    assert result.checks.metadata.format == pillow_format


@pytest.mark.parametrize(
    ("name", "fourcc"),
    [("a.mp4", "mp4v"), ("a.mov", "mp4v"), ("a.avi", "MJPG"), ("a.webm", "VP80")],
)
def test_supported_video_containers(tmp_path, name, fourcc):
    import cv2

    path = tmp_path / name
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), 10, (160, 120))
    if not writer.isOpened():
        pytest.skip(f"This OpenCV build cannot write {name} with {fourcc}.")
    for colour in ((0, 0, 255), (255, 0, 0)):
        frame = np.full((120, 160, 3), colour, dtype=np.uint8)
        for _ in range(20):
            writer.write(frame)
    writer.release()

    result = analyze_media(path, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert result.failure_code is None
    assert result.media_type is MediaType.VIDEO
    assert len(result.checks.keyframes.frames) == 2


def test_animated_image_reports_first_frame_only(tmp_path):
    path = tmp_path / "animated.webp"
    frames = [patterned_image(seed=1), patterned_image(seed=2)]
    frames[0].save(path, format="WEBP", save_all=True, append_images=frames[1:])
    result = analyze_media(path, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert any("first frame" in line for line in result.limitations)


def test_phash_distance_limit_is_inclusive():
    index = JsonHashIndex(
        [
            ReferenceEntry(phash="000000000000001f", label="distance 5"),
            ReferenceEntry(phash="000000000000003f", label="distance 6"),
        ]
    )
    assert [match.label for match in index.lookup("0000000000000000", 5)] == ["distance 5"]


def _record_model_loading(monkeypatch) -> dict:
    """Replace transformers and torch so loading options can be inspected offline."""
    calls: dict = {}

    def recorder(name):
        def from_pretrained(model_id, **options):
            calls[name] = options
            if name == "model":
                raise OSError("stop after recording")
            return object()

        return types.SimpleNamespace(from_pretrained=from_pretrained)

    fake = types.SimpleNamespace(
        AutoImageProcessor=recorder("processor"),
        AutoModelForImageClassification=recorder("model"),
    )
    monkeypatch.setitem(sys.modules, "transformers", fake)
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace())
    return calls


def test_analysis_stays_offline_by_default(monkeypatch):
    calls = _record_model_loading(monkeypatch)
    with pytest.raises(ClassifierUnavailable):
        HuggingFaceClassifier(MediaConfig()).predict([patterned_image()])
    assert calls["processor"]["local_files_only"] is True
    assert calls["model"]["local_files_only"] is True
    assert calls["model"]["use_safetensors"] is True


def test_download_needs_explicit_opt_in(monkeypatch):
    calls = _record_model_loading(monkeypatch)
    with pytest.raises(ClassifierUnavailable):
        HuggingFaceClassifier(MediaConfig(allow_model_download=True)).predict([patterned_image()])
    assert calls["model"]["local_files_only"] is False


def test_model_revision_is_pinned_when_loading(monkeypatch):
    calls = _record_model_loading(monkeypatch)
    config = MediaConfig()
    with pytest.raises(ClassifierUnavailable):
        HuggingFaceClassifier(config).predict([patterned_image()])
    assert calls["model"]["revision"] == config.model_revision
    assert calls["processor"]["revision"] == config.model_revision


def test_image_processor_implementation_is_fixed(monkeypatch):
    calls = _record_model_loading(monkeypatch)
    with pytest.raises(ClassifierUnavailable):
        HuggingFaceClassifier(MediaConfig()).predict([patterned_image()])
    assert calls["processor"]["use_fast"] is False


def test_rejected_input_has_no_check_results(tmp_path):
    result = analyze_media(tmp_path / "missing.jpg", classifier=FakeClassifier(0.9), config=MediaConfig())
    assert result.checks.classifier.status is CheckStatus.UNAVAILABLE
    assert result.evidence == []
