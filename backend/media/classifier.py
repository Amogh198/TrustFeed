"""Single-model image classifier adapter. torch and transformers load lazily."""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Protocol

from backend.media.config import MediaConfig
from backend.media.errors import ClassifierUnavailable

_SYNTHETIC_LABELS = {"fake", "deepfake", "synthetic", "ai", "aigenerated", "artificial", "manipulated"}
MODEL_FILES = ["config.json", "preprocessor_config.json", "model.safetensors"]


class ImageClassifier(Protocol):
    model_id: str
    model_revision: str | None

    def predict(self, images: Sequence[object]) -> list[float]:
        """Return the synthetic-class probability for each image."""
        ...


def synthetic_class_index(id2label: Mapping[int, str]) -> int:
    """Find the synthetic class by name, since label order differs between models."""
    matches = [
        int(index)
        for index, label in id2label.items()
        if re.sub(r"[^a-z]", "", str(label).casefold()) in _SYNTHETIC_LABELS
    ]
    if len(matches) != 1:
        raise ClassifierUnavailable("The model's labels do not identify a single synthetic class.")
    return matches[0]


class HuggingFaceClassifier:
    def __init__(self, config: MediaConfig) -> None:
        self.model_id = config.model_id
        self.model_revision = config.model_revision
        self._allow_download = config.allow_model_download
        self._device_setting = config.device
        self._batch_size = max(1, config.batch_size)
        self._lock = threading.Lock()
        self._loaded: tuple[object, object, int, str] | None = None

    def _load(self) -> tuple[object, object, int, str]:
        with self._lock:
            if self._loaded is not None:
                return self._loaded
            try:
                import torch
                from transformers import AutoImageProcessor, AutoModelForImageClassification
            except Exception as exc:
                raise ClassifierUnavailable(
                    "Model dependencies are not installed (see backend/media/requirements-model.txt)."
                ) from exc
            try:
                options = {"revision": self.model_revision, "local_files_only": not self._allow_download}
                # Fixed so a transformers default change cannot shift scores.
                processor = AutoImageProcessor.from_pretrained(self.model_id, use_fast=False, **options)
                # safetensors only: pickle-based weights can execute code when loaded.
                model = AutoModelForImageClassification.from_pretrained(self.model_id, use_safetensors=True, **options)
            except Exception as exc:
                raise ClassifierUnavailable(
                    "Model weights are not available locally. "
                    "Run: python -m backend.media download-model (or download-panel for every panel detector)"
                ) from exc
            target = synthetic_class_index(model.config.id2label)
            device = self._device_setting
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            try:
                model.to(device).eval()
            except Exception as exc:
                raise ClassifierUnavailable(f"The model could not be loaded on device {device!r}.") from exc
            self._loaded = (model, processor, target, device)
            return self._loaded

    def predict(self, images: Sequence[object]) -> list[float]:
        model, processor, target, device = self._load()
        import torch

        scores: list[float] = []
        try:
            with torch.inference_mode():
                for start in range(0, len(images), self._batch_size):
                    batch = list(images[start : start + self._batch_size])
                    inputs = processor(images=batch, return_tensors="pt").to(device)
                    probabilities = torch.softmax(model(**inputs).logits, dim=-1)[:, target]
                    scores.extend(float(value) for value in probabilities.cpu())
        except (RuntimeError, ValueError) as exc:
            raise ClassifierUnavailable(f"Model inference failed ({type(exc).__name__}).") from exc
        return scores


@lru_cache(maxsize=2)
def _cached_classifier(config: MediaConfig) -> HuggingFaceClassifier:
    return HuggingFaceClassifier(config)


def default_classifier(config: MediaConfig) -> ImageClassifier:
    return _cached_classifier(config)


def download_model(config: MediaConfig) -> str:
    """Download only the safetensors weights and config files for offline use."""
    from huggingface_hub import snapshot_download

    return snapshot_download(config.model_id, revision=config.model_revision, allow_patterns=MODEL_FILES)
