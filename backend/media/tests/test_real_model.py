"""Runs the default model. Skipped unless its weights have been downloaded."""

from __future__ import annotations

import pytest

from backend.media import MediaConfig, analyze_media
from backend.media.classifier import build_classifier
from backend.media.errors import ClassifierUnavailable
from backend.media.models import CheckStatus
from backend.media.tests.helpers import patterned_image


@pytest.fixture(scope="module")
def real_classifier():
    pytest.importorskip("torch")
    classifier = build_classifier(MediaConfig(device="cpu"))
    try:
        classifier.predict([patterned_image()])
    except ClassifierUnavailable as exc:
        pytest.skip(str(exc))
    return classifier


def test_pinned_model_scores_an_image(real_classifier, image_file):
    result = analyze_media(image_file, classifier=real_classifier, config=MediaConfig())
    assert result.status is CheckStatus.COMPLETE
    assert 0 <= result.score <= 1
    assert result.confidence is None
    assert result.checks.classifier.model_revision == MediaConfig().model_revision


def test_pinned_model_scores_a_video(real_classifier, video_file):
    result = analyze_media(video_file, classifier=real_classifier, config=MediaConfig())
    assert result.status is CheckStatus.COMPLETE
    assert result.checks.classifier.items_scored == 2
    assert all(0 <= frame.model_score <= 1 for frame in result.checks.keyframes.frames)
