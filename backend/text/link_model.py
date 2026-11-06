"""Score a host name with the small model from ``train_link_model.py``. Runs locally and sends nothing.

The weights load with pickle turned off. A missing file means no score, never a low one.
"""

from __future__ import annotations

import math
import zlib
from pathlib import Path

MODEL_PATH = Path(__file__).parent / "link_model.npz"
SIZE = 2**18
_loaded: tuple[list[float], float] | None = None
_tried = False


def features(host: str) -> list[int]:
    """Hash runs of 3 to 5 letters, so similar names share weights."""
    text = f"^{host}$"
    return [
        zlib.crc32(text[start : start + size].encode("utf-8", "replace")) % SIZE
        for size in (3, 4, 5)
        for start in range(len(text) - size + 1)
    ]


def reset() -> None:
    global _loaded, _tried
    _loaded, _tried = None, False


def _load() -> tuple[list[float], float] | None:
    global _loaded, _tried
    if not _tried:
        _tried = True
        try:
            import numpy as np

            with np.load(MODEL_PATH, allow_pickle=False) as data:
                _loaded = (data["weights"].tolist(), float(data["bias"][0]))
        except (OSError, ValueError, KeyError, ImportError):
            _loaded = None
    return _loaded


def score_host(host: str) -> float | None:
    """Return a phishing likelihood from 0 to 1, or None when the model can't score this host."""
    model = _load()
    items = features(host.casefold())
    if model is None or not items:
        return None
    weights, bias = model
    margin = bias + sum(weights[i] for i in items) / math.sqrt(len(items))
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, margin))))
