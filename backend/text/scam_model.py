"""Optional phishing model, tested alongside the scam rules.

It was trained on emails and URLs, not social posts, so its score is reported on its
own and is never taken as a finding. Weights are never fetched while analysing a
case, only by ``python -m backend.text download-scam-model``.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from backend.text.ner import _hub_cache

# Never log the text or its score: they come from what a user submitted.
logger = logging.getLogger(__name__)

MODEL_ID = "cybersectony/phishing-email-detection-distilbert_v2.4.1"
# Pinned so that a change upstream cannot silently change results.
MODEL_REVISION = "6724dec17360ab1f6450553f1d950404f66a5dde"
# safetensors only: pickle-based weights can execute code when loaded.
MODEL_FILES = ["config.json", "model.safetensors", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.txt"]
DOWNLOAD_HINT = "Run: python -m backend.text download-scam-model"
# The model's config only says LABEL_0 to LABEL_3. These names come from its model card.
LABEL_NAMES = ("legitimate_email", "phishing_url", "legitimate_url", "phishing_url_alt")
PHISHING_LABELS = (1, 3)
PHISHING_THRESHOLD = 0.5
DEFAULT_TIMEOUT_SECONDS = 20.0
_MAX_TOKENS = 512
_BATCH_SIZE = 16


class PhishingUnavailable(RuntimeError):
    """The model cannot run. The message is shown to the user, so it holds no content."""


class PhishingBackend(Protocol):
    def is_ready(self) -> str | None:
        """Return why the model cannot run, cheaply and without loading it, or None."""
        ...

    def predict(self, texts: Sequence[str]) -> list[float]: ...


@dataclass(frozen=True)
class PhishingOutcome:
    status: str
    reason: str | None = None
    score: float | None = None


def weights_path():
    name = f"models--{MODEL_ID.replace('/', '--')}"
    return _hub_cache() / name / "snapshots" / MODEL_REVISION / "model.safetensors"


class HuggingFacePhishing:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded: tuple[object, object] | None = None

    def is_ready(self) -> str | None:
        if self._loaded is None and not weights_path().exists():
            return f"The {MODEL_ID} model has not been downloaded. {DOWNLOAD_HINT}"
        return None

    def _load(self) -> tuple[object, object]:
        with self._lock:
            if self._loaded is not None:
                return self._loaded
            try:
                from transformers import (
                    AutoModelForSequenceClassification,
                    AutoTokenizer,
                )
            except Exception as exc:
                raise PhishingUnavailable("Model packages are not installed (see backend/text/requirements-model.txt).") from exc
            try:
                options = {"revision": MODEL_REVISION, "local_files_only": True}
                tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **options)
                model = AutoModelForSequenceClassification.from_pretrained(MODEL_ID, use_safetensors=True, **options).eval()
            except Exception as exc:
                raise PhishingUnavailable(f"The {MODEL_ID} model could not be loaded. {DOWNLOAD_HINT}") from exc
            self._loaded = (tokenizer, model)
            return self._loaded

    def probabilities(self, texts: Sequence[str]) -> list[list[float]]:
        """One probability per entry in ``LABEL_NAMES``, for each text."""
        tokenizer, model = self._load()
        import torch

        rows: list[list[float]] = []
        with torch.inference_mode():
            for start in range(0, len(texts), _BATCH_SIZE):
                batch = tokenizer(  # type: ignore[operator]
                    list(texts[start : start + _BATCH_SIZE]), padding=True, truncation=True, max_length=_MAX_TOKENS,
                    return_tensors="pt",
                )
                output = torch.softmax(model(**batch).logits, dim=-1)  # type: ignore[operator]
                rows.extend([round(float(value), 4) for value in row] for row in output)
        return rows

    def predict(self, texts: Sequence[str]) -> list[float]:
        return [round(sum(row[index] for index in PHISHING_LABELS), 4) for row in self.probabilities(texts)]


class PhishingRunner:
    """Run one prediction at a time under a time limit, and report rather than raise."""

    def __init__(self, backend: PhishingBackend, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._backend = backend
        self._timeout = timeout_seconds
        self._busy = threading.Lock()

    def run(self, text: str) -> PhishingOutcome:
        reason = self._backend.is_ready()
        if reason:
            return PhishingOutcome("unavailable", reason)
        # A timed-out call keeps its thread, because Python cannot stop it, so later calls report it.
        if not self._busy.acquire(blocking=False):
            return PhishingOutcome("unavailable", "The model is still busy with an earlier request.")
        box: dict[str, object] = {}
        finished = threading.Event()

        def work() -> None:
            try:
                box["score"] = self._backend.predict([text])[0]
            except Exception as exc:  # noqa: BLE001 - Reported to the caller below.
                box["error"] = exc
            finally:
                self._busy.release()
                finished.set()

        threading.Thread(target=work, daemon=True, name="text-phishing").start()
        if not finished.wait(self._timeout):
            return PhishingOutcome("unavailable", f"The model did not finish within {self._timeout:g} seconds.")
        error = box.get("error")
        if isinstance(error, PhishingUnavailable):
            return PhishingOutcome("unavailable", str(error))
        if error is not None:
            logger.warning("Phishing model failed: %s", type(error).__name__)
            return PhishingOutcome("unavailable", "The model failed while reading this text.")
        return PhishingOutcome("complete", score=box["score"])  # type: ignore[arg-type]


def _timeout_from_env() -> float:
    try:
        value = float(os.getenv("TEXT_SCAM_MODEL_TIMEOUT_SECONDS", ""))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


_default_runner: PhishingRunner | None = None


def default_runner() -> PhishingRunner:
    global _default_runner
    if _default_runner is None:
        _default_runner = PhishingRunner(HuggingFacePhishing(), _timeout_from_env())
    return _default_runner


def download_model() -> str:
    """Fetch only the pinned safetensors weights and config files. Run by hand, never by the API."""
    from huggingface_hub import snapshot_download

    # One worker: huggingface_hub's symlink check races across threads on Windows.
    return snapshot_download(MODEL_ID, revision=MODEL_REVISION, allow_patterns=MODEL_FILES, max_workers=1)
