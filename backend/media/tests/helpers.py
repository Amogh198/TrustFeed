"""Shared test helpers, in a uniquely named module so other lanes' conftest files cannot shadow them."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


class FakeClassifier:
    """Deterministic stand-in so pipeline tests do not depend on model weights."""

    model_id = "test/fake-model"
    model_revision = "test-revision"

    def __init__(self, score: float | list[float] = 0.5, error: Exception | None = None) -> None:
        self.score = score
        self.error = error
        self.seen = 0

    def predict(self, images):
        self.seen += len(images)
        if self.error:
            raise self.error
        if isinstance(self.score, list):
            return self.score[: len(images)]
        return [self.score] * len(images)


def patterned_image(seed: int = 1, size: int = 256) -> Image.Image:
    """Smooth random pattern with enough low-frequency structure for pHash."""
    generator = np.random.default_rng(seed)
    coarse = generator.integers(0, 256, (8, 8, 3), dtype=np.uint8)
    return Image.fromarray(coarse).resize((size, size), Image.Resampling.BICUBIC)


def write_video(path: Path, scenes: list[tuple[tuple[int, int, int], float]], fps: int = 10) -> Path:
    """Write solid-colour scenes, given as (BGR colour, seconds), to an MP4 file."""
    import cv2

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (160, 120))
    assert writer.isOpened()
    for colour, seconds in scenes:
        frame = np.full((120, 160, 3), colour, dtype=np.uint8)
        for _ in range(int(seconds * fps)):
            writer.write(frame)
    writer.release()
    return path
