"""The detectors the panel runs, each pinned, and how to build and download them."""

from __future__ import annotations

from dataclasses import replace

from backend.media.classifier import HuggingFaceClassifier, ImageClassifier, download_model
from backend.media.config import DEFAULT_MODEL_ID, DEFAULT_MODEL_REVISION, MediaConfig
from backend.media.nonescape import (
    NONESCAPE_MODEL_ID,
    NONESCAPE_SHA256,
    NonescapeMiniClassifier,
    download_nonescape,
)

# Hugging Face models are pinned to a commit and Nonescape to its file's SHA-256.
# Every licence is Apache 2.0, and every model loads from safetensors.
PANEL_MODELS: tuple[tuple[str, str], ...] = (
    (DEFAULT_MODEL_ID, DEFAULT_MODEL_REVISION),
    ("haywoodsloan/ai-image-detector-deploy", "4ae1822603cb1ec980c217cfde1ef1b8e0477a16"),
    ("prithivMLmods/Deep-Fake-Detector-v2-Model", "3a99ae26f52c7ac7c3a53103b6cf3a8b617f7093"),
    ("prithivMLmods/open-deepfake-detection", "aaa680d8ff799424ba5d092b6d5e0b999f0e0ab6"),
    ("Ateeqq/ai-vs-human-image-detector", "60e82406916921b823616bee33397baab38af3f0"),
    (NONESCAPE_MODEL_ID, NONESCAPE_SHA256),
)


def build_classifier(config: MediaConfig) -> ImageClassifier:
    """Build a detector without loading it. Weights load on first use."""
    if config.model_id == NONESCAPE_MODEL_ID:
        return NonescapeMiniClassifier(device=config.device, batch_size=config.batch_size)
    return HuggingFaceClassifier(config)


def download_panel(config: MediaConfig) -> list[str]:
    """Download every panel model's safetensors weights. Analysis never calls this."""
    locations = []
    for model_id, revision in PANEL_MODELS:
        if model_id == NONESCAPE_MODEL_ID:
            locations.append(str(download_nonescape()))
        else:
            locations.append(download_model(replace(config, model_id=model_id, model_revision=revision)))
    return locations
