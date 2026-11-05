"""Optional named-entity model. Everything still runs, and says so, when it is missing.

Weights are never fetched while analysing a case. They arrive only through the
explicit ``python -m backend.text download-ner`` command. torch and transformers
load on first use, and a separate thread applies the time limit, so a slow model
cannot hold up the response.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

# Never log the text or the entities: they come from what a user submitted.
logger = logging.getLogger(__name__)

MODEL_ID = "dslim/bert-base-NER"
# Pinned so that a change upstream cannot silently change results.
MODEL_REVISION = "d1a3e8f13f8c3566299d95fcfc9a8d2382a9affc"
# safetensors only: pickle-based weights can execute code when loaded.
MODEL_FILES = [
    "config.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json", "vocab.txt",
    "model.safetensors",
]
DOWNLOAD_HINT = "Run: python -m backend.text download-ner"
DEFAULT_TIMEOUT_SECONDS = 20.0
MIN_ENTITY_SCORE = 0.6
# Comfortably under the model's 512-token limit for ordinary text.
MAX_CHARS_PER_TEXT = 800
_ENTITY_TYPES = {"PER": "person", "ORG": "organization", "LOC": "place", "MISC": "other"}


class NerUnavailable(RuntimeError):
    """The model cannot run. The message is shown to the user, so it holds no content."""


@dataclass(frozen=True)
class ModelEntity:
    text: str
    type: str
    score: float
    start: int
    end: int


@dataclass(frozen=True)
class NerOutcome:
    status: str
    reason: str | None = None
    entities: list[list[ModelEntity]] = field(default_factory=list)


class NerBackend(Protocol):
    def is_ready(self) -> str | None:
        """Return why the model cannot run, cheaply and without loading it, or None."""
        ...

    def predict(self, texts: Sequence[str]) -> list[list[ModelEntity]]: ...


def _hub_cache() -> Path:
    explicit = os.getenv("HF_HUB_CACHE") or os.getenv("HUGGINGFACE_HUB_CACHE")
    if explicit:
        return Path(explicit)
    home = os.getenv("HF_HOME")
    return Path(home) / "hub" if home else Path.home() / ".cache" / "huggingface" / "hub"


def weights_path() -> Path:
    return _hub_cache() / f"models--{MODEL_ID.replace('/', '--')}" / "snapshots" / MODEL_REVISION / "model.safetensors"


class HuggingFaceNer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pipeline: object | None = None

    def is_ready(self) -> str | None:
        if self._pipeline is None and not weights_path().exists():
            return f"The {MODEL_ID} model has not been downloaded. {DOWNLOAD_HINT}"
        return None

    def _load(self) -> object:
        with self._lock:
            if self._pipeline is not None:
                return self._pipeline
            try:
                from transformers import (
                    AutoModelForTokenClassification,
                    AutoTokenizer,
                    pipeline,
                )
            except Exception as exc:
                raise NerUnavailable(
                    "Model packages are not installed (see backend/text/requirements-model.txt)."
                ) from exc
            try:
                options = {"revision": MODEL_REVISION, "local_files_only": True}
                tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **options)
                model = AutoModelForTokenClassification.from_pretrained(MODEL_ID, use_safetensors=True, **options)
                self._pipeline = pipeline(
                    "token-classification", model=model, tokenizer=tokenizer, aggregation_strategy="simple", device=-1
                )
            except Exception as exc:
                raise NerUnavailable(f"The {MODEL_ID} model could not be loaded. {DOWNLOAD_HINT}") from exc
            return self._pipeline

    def predict(self, texts: Sequence[str]) -> list[list[ModelEntity]]:
        recognize = self._load()
        results: list[list[ModelEntity]] = []
        for text in texts:
            found: list[ModelEntity] = []
            for item in recognize(text[:MAX_CHARS_PER_TEXT]):  # type: ignore[operator]
                kind = _ENTITY_TYPES.get(str(item["entity_group"]))
                if kind is None or float(item["score"]) < MIN_ENTITY_SCORE:
                    continue
                start, end = int(item["start"]), int(item["end"])
                found.append(ModelEntity(text[start:end].strip(), kind, round(float(item["score"]), 3), start, end))
            results.append(found)
        return results


class NerRunner:
    """Run one prediction at a time under a time limit, and report rather than raise."""

    def __init__(self, backend: NerBackend, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._backend = backend
        self._timeout = timeout_seconds
        self._busy = threading.Lock()

    def run(self, texts: Sequence[str]) -> NerOutcome:
        if not texts:
            return NerOutcome("not_applicable", "There were no factual claims to run the model on.")
        reason = self._backend.is_ready()
        if reason:
            return NerOutcome("unavailable", reason)
        # A timed-out call keeps its thread, because Python cannot stop it. Waiting
        # here would pile up requests behind a stuck model, so later calls report it.
        if not self._busy.acquire(blocking=False):
            return NerOutcome("unavailable", "The model is still busy with an earlier request.")
        box: dict[str, object] = {}
        finished = threading.Event()

        def work() -> None:
            try:
                box["entities"] = self._backend.predict(list(texts))
            except Exception as exc:  # noqa: BLE001 - Reported to the caller below.
                box["error"] = exc
            finally:
                self._busy.release()
                finished.set()

        threading.Thread(target=work, daemon=True, name="text-ner").start()
        if not finished.wait(self._timeout):
            return NerOutcome("unavailable", f"The model did not finish within {self._timeout:g} seconds.")
        error = box.get("error")
        if isinstance(error, NerUnavailable):
            return NerOutcome("unavailable", str(error))
        if error is not None:
            logger.warning("Entity model failed: %s", type(error).__name__)
            return NerOutcome("unavailable", "The model failed while reading this text.")
        return NerOutcome("complete", entities=box["entities"])  # type: ignore[arg-type]


def _timeout_from_env() -> float:
    try:
        value = float(os.getenv("TEXT_NER_TIMEOUT_SECONDS", ""))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


_default_runner: NerRunner | None = None


def default_runner() -> NerRunner:
    global _default_runner
    if _default_runner is None:
        _default_runner = NerRunner(HuggingFaceNer(), _timeout_from_env())
    return _default_runner


def download_model() -> str:
    """Fetch only the pinned safetensors weights and config files. Run by hand, never by the API."""
    from huggingface_hub import snapshot_download

    return snapshot_download(MODEL_ID, revision=MODEL_REVISION, allow_patterns=MODEL_FILES, max_workers=1)
