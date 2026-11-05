"""Adapter for the Nonescape mini detector. torch and torchvision load lazily.

The model definition and preprocessing follow https://github.com/e3ntity/nonescape at commit
52619d5c96ab83f018d9e879d4be14d847ccb15d, Copyright 2025 Aedilic Inc., Apache License 2.0.
Its package pins older library versions, so only these few lines are reproduced here.

Its weights are not on Hugging Face, so they can't be pinned to a commit. A SHA-256 pins them instead.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from backend.media.errors import ClassifierUnavailable

NONESCAPE_MODEL_ID = "nonescape/nonescape-mini-v0"
NONESCAPE_SHA256 = "7a0d0740c813ce199bc32ed16a5f4f4915895c4c9fdee0a98bdbeedd4f3631fd"
NONESCAPE_URL = "https://nonescape.sfo2.cdn.digitaloceanspaces.com/nonescape-mini-v0.safetensors"
# Its own examples read the synthetic probability from this class.
_SYNTHETIC_INDEX = 1
_CHUNK = 1024 * 1024


def nonescape_path() -> Path:
    configured = os.environ.get("MEDIA_NONESCAPE_PATH", "").strip()
    if configured:
        return Path(configured)
    return Path.home() / ".cache" / "trustfeed" / "nonescape" / "nonescape-mini-v0.safetensors"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def download_nonescape(path: Path | None = None, *, url: str = NONESCAPE_URL, expected: str = NONESCAPE_SHA256) -> Path:
    """Download the weights, keeping them only if they match the pinned hash."""
    target = path or nonescape_path()
    if target.is_file() and _sha256(target) == expected:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "TrustFeed-model-download/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out, _CHUNK)
    if _sha256(partial) != expected:
        partial.unlink()
        raise ValueError("The downloaded Nonescape weights do not match the pinned SHA-256.")
    partial.replace(target)
    return target


class NonescapeMiniClassifier:
    model_id = NONESCAPE_MODEL_ID
    model_revision = NONESCAPE_SHA256

    def __init__(self, path: Path | None = None, device: str = "auto", batch_size: int = 8) -> None:
        self._path = path or nonescape_path()
        self._device_setting = device
        self._batch_size = max(1, batch_size)
        self._lock = threading.Lock()
        self._loaded: tuple[object, object, str] | None = None

    def _load(self) -> tuple[object, object, str]:
        with self._lock:
            if self._loaded is not None:
                return self._loaded
            try:
                import torch
                import torchvision.transforms.v2 as transforms
                from safetensors.torch import load_file
                from torch import nn
                from torchvision.models import efficientnet_v2_s
            except Exception as exc:
                raise ClassifierUnavailable(
                    "Model dependencies are not installed (see backend/media/requirements-model.txt)."
                ) from exc
            if not self._path.is_file():
                raise ClassifierUnavailable(
                    "Model weights are not available locally. Run: python -m backend.media download-panel"
                )
            if _sha256(self._path) != self.model_revision:
                raise ClassifierUnavailable("The Nonescape weights on disk do not match the pinned SHA-256.")

            class _Mini(nn.Module):
                def __init__(self) -> None:
                    super().__init__()
                    self.backbone = efficientnet_v2_s(weights=None, num_classes=1024, dropout=0.2)
                    self.head = nn.Linear(1024, 2)

                def forward(self, batch):
                    return torch.softmax(self.head(self.backbone(batch)), dim=-1)

            device = self._device_setting
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            try:
                model = _Mini()
                model.load_state_dict(load_file(self._path))
                model.to(device).eval()
            except Exception as exc:
                raise ClassifierUnavailable("The Nonescape weights could not be loaded.") from exc
            transform = transforms.Compose(
                [
                    transforms.ToImage(),
                    transforms.Resize(256),
                    transforms.CenterCrop(224),
                    transforms.JPEG(quality=100),
                    transforms.ToDtype(torch.float32, scale=True),
                    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
                ]
            )
            self._loaded = (model, transform, device)
            return self._loaded

    def predict(self, images: Sequence[object]) -> list[float]:
        model, transform, device = self._load()
        import torch

        scores: list[float] = []
        try:
            with torch.inference_mode():
                for start in range(0, len(images), self._batch_size):
                    batch = [transform(image.convert("RGB")) for image in images[start : start + self._batch_size]]
                    probabilities = model(torch.stack(batch).to(device))[:, _SYNTHETIC_INDEX]
                    scores.extend(float(value) for value in probabilities.cpu())
        except (RuntimeError, ValueError) as exc:
            raise ClassifierUnavailable(f"Model inference failed ({type(exc).__name__}).") from exc
        return scores
