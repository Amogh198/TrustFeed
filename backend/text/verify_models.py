"""Optional models that compare a claim with evidence.

all-MiniLM-L6-v2 finds the passages about the same thing. DeBERTa then judges
whether a passage entails or contradicts the claim. Weights are never fetched while
analysing a case, only by ``python -m backend.text download-verification``. torch and
transformers load on first use. Both scores are signals, not probabilities of truth.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from backend.text.ner import _hub_cache

EMBEDDER_ID = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDER_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBEDDER_FILES = [
    "config.json", "config_sentence_transformers.json", "modules.json", "sentence_bert_config.json",
    "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.txt", "model.safetensors",
    "1_Pooling/config.json",
]
NLI_ID = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
NLI_REVISION = "6f5cf0a2b59cabb106aca4c287eed12e357e90eb"
NLI_FILES = [
    "added_tokens.json", "config.json", "special_tokens_map.json", "spm.model", "tokenizer.json",
    "tokenizer_config.json", "model.safetensors",
]
DOWNLOAD_HINT = "Run: python -m backend.text download-verification"
_BATCH_SIZE = 16
_MAX_TOKENS = 256


class ComparisonUnavailable(RuntimeError):
    """The models cannot run. The message is shown to the user, so it holds no content."""


@dataclass(frozen=True)
class Entailment:
    entailment: float
    neutral: float
    contradiction: float


class Comparer(Protocol):
    def is_ready(self) -> str | None:
        """Return why comparison cannot run, cheaply and without loading anything, or None."""
        ...

    def similarity(self, claim: str, passages: Sequence[str]) -> list[float]: ...

    def entail(self, pairs: Sequence[tuple[str, str]]) -> list[Entailment]:
        """Each pair is (premise, hypothesis)."""
        ...


def _weights_exist(model_id: str, revision: str) -> bool:
    name = f"models--{model_id.replace('/', '--')}"
    return (_hub_cache() / name / "snapshots" / revision / "model.safetensors").exists()


class HuggingFaceComparer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded: tuple[object, object, object, object, dict[str, int]] | None = None

    def is_ready(self) -> str | None:
        if self._loaded is not None:
            return None
        missing = [
            model_id
            for model_id, revision in ((EMBEDDER_ID, EMBEDDER_REVISION), (NLI_ID, NLI_REVISION))
            if not _weights_exist(model_id, revision)
        ]
        return f"These models have not been downloaded: {', '.join(missing)}. {DOWNLOAD_HINT}" if missing else None

    def _load(self) -> tuple[object, object, object, object, dict[str, int]]:
        with self._lock:
            if self._loaded is not None:
                return self._loaded
            try:
                from transformers import (  # pyright: ignore[reportMissingImports]
                    AutoModel,
                    AutoModelForSequenceClassification,
                    AutoTokenizer,
                )
            except Exception as exc:
                raise ComparisonUnavailable(
                    "Model packages are not installed (see backend/text/requirements-model.txt)."
                ) from exc
            try:
                embed_options = {"revision": EMBEDDER_REVISION, "local_files_only": True}
                nli_options = {"revision": NLI_REVISION, "local_files_only": True}
                embed_tokenizer = AutoTokenizer.from_pretrained(EMBEDDER_ID, **embed_options)
                # safetensors only: pickle-based weights can execute code when loaded.
                embedder = AutoModel.from_pretrained(EMBEDDER_ID, use_safetensors=True, **embed_options).eval()
                nli_tokenizer = AutoTokenizer.from_pretrained(NLI_ID, **nli_options)
                nli = AutoModelForSequenceClassification.from_pretrained(NLI_ID, use_safetensors=True, **nli_options).eval()
            except Exception as exc:
                raise ComparisonUnavailable(f"The comparison models could not be loaded. {DOWNLOAD_HINT}") from exc
            # Read from the model, since label order differs between models.
            labels = {str(label).casefold(): int(index) for index, label in nli.config.id2label.items()}
            if not {"entailment", "neutral", "contradiction"} <= set(labels):
                raise ComparisonUnavailable("The comparison model's labels were not the expected ones.")
            self._loaded = (embed_tokenizer, embedder, nli_tokenizer, nli, labels)
            return self._loaded

    def similarity(self, claim: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        tokenizer, model, *_ = self._load()
        import torch  # pyright: ignore[reportMissingImports]

        texts = [claim, *passages]
        vectors = []
        with torch.inference_mode():
            for start in range(0, len(texts), _BATCH_SIZE):
                batch = tokenizer(  # type: ignore[operator]
                    texts[start : start + _BATCH_SIZE], padding=True, truncation=True, max_length=_MAX_TOKENS,
                    return_tensors="pt",
                )
                output = model(**batch).last_hidden_state  # type: ignore[operator]
                mask = batch["attention_mask"].unsqueeze(-1).float()
                pooled = (output * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                vectors.append(torch.nn.functional.normalize(pooled, dim=1))
        joined = torch.cat(vectors)
        return [round(float(value), 4) for value in (joined[1:] @ joined[0])]

    def entail(self, pairs: Sequence[tuple[str, str]]) -> list[Entailment]:
        if not pairs:
            return []
        _, _, tokenizer, model, labels = self._load()
        import torch  # pyright: ignore[reportMissingImports]

        results: list[Entailment] = []
        with torch.inference_mode():
            for start in range(0, len(pairs), _BATCH_SIZE):
                chunk = pairs[start : start + _BATCH_SIZE]
                batch = tokenizer(  # type: ignore[operator]
                    [pair[0] for pair in chunk], [pair[1] for pair in chunk], padding=True, truncation=True,
                    max_length=_MAX_TOKENS, return_tensors="pt",
                )
                for row in torch.softmax(model(**batch).logits, dim=-1):  # type: ignore[operator]
                    results.append(
                        Entailment(
                            round(float(row[labels["entailment"]]), 4),
                            round(float(row[labels["neutral"]]), 4),
                            round(float(row[labels["contradiction"]]), 4),
                        )
                    )
        return results


def download_models() -> list[str]:
    """Fetch only the pinned safetensors weights and config files. Run by hand, never by the API."""
    from huggingface_hub import snapshot_download  # pyright: ignore[reportMissingImports]

    # One worker: huggingface_hub's symlink check races across threads on Windows.
    return [
        snapshot_download(EMBEDDER_ID, revision=EMBEDDER_REVISION, allow_patterns=EMBEDDER_FILES, max_workers=1),
        snapshot_download(NLI_ID, revision=NLI_REVISION, allow_patterns=NLI_FILES, max_workers=1),
    ]
