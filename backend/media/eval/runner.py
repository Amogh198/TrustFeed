"""Runs detectors over labelled folders and writes a results file with no images or file names."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from backend.media.analyzer import analyze_media
from backend.media.classifier import HuggingFaceClassifier, ImageClassifier
from backend.media.config import DEFAULT_MODEL_ID, DEFAULT_MODEL_REVISION, MediaConfig
from backend.media.errors import MediaInputError
from backend.media.eval.metrics import FAKE, REAL, Scored, at_threshold, choose_threshold, evaluate
from backend.media.metadata import inspect_input, read_image
from backend.media.models import CheckStatus, MediaType
from backend.media.phash import compute_phash

SCHEMA = "media-eval-1"
UNCATEGORIZED = "uncategorized"
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_PINNED = re.compile(r"[0-9a-f]{40}")
NOTICE = (
    "Measured on the listed images only. These figures do not predict results on other kinds of image, and no single "
    "result from this detector proves that an image is authentic or false."
)
LIMITATIONS = (
    "Recall counts inconclusive results as not flagged.",
    "Images in one split can still be near-duplicates of images in the other, unless they share a perceptual hash.",
    "Labels and licences are as stated by whoever ran this benchmark. The tool does not check them.",
)
ClassifierFactory = Callable[[MediaConfig], ImageClassifier]


@dataclass(frozen=True)
class Item:
    path: Path
    label: str
    category: str
    split: str


@dataclass(frozen=True)
class Dataset:
    items: tuple[Item, ...]
    duplicates_removed: int
    label_conflicts: int
    unreadable: int
    skipped_other_types: int


def parse_source(text: str) -> dict[str, str]:
    """Read "name|licence|url". A benchmark must say what its data is and what allows its use."""
    parts = [part.strip() for part in text.split("|")]
    if len(parts) != 3 or not parts[0] or not parts[1]:
        raise ValueError('A source must look like "name|licence|url".')
    return {"name": parts[0], "licence": parts[1], "url": parts[2]}


def parse_model(text: str) -> tuple[str, str]:
    """Read "org/name@revision". Only a full commit hash pins what is being measured."""
    model_id, _, revision = text.partition("@")
    if not model_id or not _PINNED.fullmatch(revision):
        raise ValueError(f"Model {text!r} must look like org/name@<40-character commit hash>.")
    return model_id, revision


def _category(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    if len(relative.parts) < 2:
        return UNCATEGORIZED
    return re.sub(r"[^a-z0-9_-]+", "_", relative.parts[0].casefold()).strip("_") or UNCATEGORIZED


def _split_of(group: str, seed: int, calibration_fraction: float) -> str:
    digest = hashlib.sha256(f"{seed}:{group}".encode()).digest()
    position = int.from_bytes(digest[:8], "big") / 2**64
    return "calibration" if position < calibration_fraction else "test"


def build_dataset(
    real_dir: Path, fake_dir: Path, config: MediaConfig, *, seed: int = 0, calibration_fraction: float = 0.5
) -> Dataset:
    """Find usable images, drop duplicates and split them.

    Copies with the same perceptual hash always share a split, so a recompressed copy
    cannot help choose a threshold and then also be used to report it.
    """
    records: dict[str, tuple[Path, str, str, str]] = {}
    labels: dict[str, set[str]] = {}
    duplicates = unreadable = skipped = 0
    for root, label in ((real_dir, REAL), (fake_dir, FAKE)):
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if path.suffix.casefold() not in _IMAGE_SUFFIXES:
                skipped += 1
                continue
            try:
                info = inspect_input(path, config)
                if info.media_type is not MediaType.IMAGE:
                    skipped += 1
                    continue
                image, _, _ = read_image(path, config)
                phash = compute_phash(image)
            except (MediaInputError, OSError, ValueError):
                unreadable += 1
                continue
            seen = labels.setdefault(info.sha256, set())
            if label in seen:
                duplicates += 1
                continue
            seen.add(label)
            if info.sha256 not in records:
                records[info.sha256] = (path, label, _category(root, path), phash)

    # The same file under both labels cannot be scored against either of them.
    conflicts = {sha for sha, seen in labels.items() if len(seen) > 1}
    items = tuple(
        Item(path, label, category, _split_of(phash, seed, calibration_fraction))
        for sha, (path, label, category, phash) in records.items()
        if sha not in conflicts
    )
    return Dataset(items, duplicates, len(conflicts), unreadable, skipped)


def _score_all(items: Sequence[Item], classifier: ImageClassifier, config: MediaConfig) -> tuple[list, int, str | None]:
    scored: list[tuple[Item, Scored]] = []
    missing = 0
    reason = None
    for position, item in enumerate(items, start=1):
        result = analyze_media(item.path, classifier=classifier, config=config)
        check = result.checks.classifier
        if check.status is CheckStatus.COMPLETE and check.score is not None and check.band is not None:
            scored.append((item, Scored(item.label, check.score, check.band.value, item.category)))
        else:
            missing += 1
            reason = reason or (check.limitations[0] if check.limitations else "No model result.")
        if position % 100 == 0:
            print(f"  scored {position} of {len(items)}", file=sys.stderr, flush=True)
    return scored, missing, reason


def _model_result(
    model_id: str, revision: str | None, classifier: ImageClassifier, items: Sequence[Item], config: MediaConfig
) -> dict:
    scored, missing, reason = _score_all(items, classifier, config)
    base = {"model_id": model_id, "model_revision": revision, "scored": len(scored), "not_scored": missing}
    if not scored:
        return {**base, "status": "unavailable", "reason": reason or "There were no images to score."}

    everything = [entry for _, entry in scored]
    calibration = [entry for item, entry in scored if item.split == "calibration"]
    test = [entry for item, entry in scored if item.split == "test"]
    cut, why_not = choose_threshold(calibration)
    categories = sorted({entry.category for entry in everything})
    return {
        **base,
        "status": "complete",
        # These bands were fixed before this data was seen, so all of it can measure them.
        "current_bands": {"all_images": evaluate(everything), "test_split": evaluate(test)},
        "best_threshold": {
            "value": round(cut, 4) if cut is not None else None,
            "chosen_on": "calibration split",
            "not_chosen_because": why_not,
            "calibration_n": len(calibration),
            # Measured only on images that played no part in choosing it.
            "test_split": at_threshold(test, cut) if cut is not None else None,
        },
        "by_category": {
            name: evaluate([entry for entry in everything if entry.category == name]) for name in categories
        },
    }


def run_benchmark(
    real_dir: Path,
    fake_dir: Path,
    *,
    sources: Sequence[dict[str, str]],
    models: Sequence[tuple[str, str | None]] | None = None,
    seed: int = 0,
    calibration_fraction: float = 0.5,
    classifier_factory: ClassifierFactory = HuggingFaceClassifier,
) -> dict:
    # A reference list would flag known images whatever the model says, so it stays off.
    config = replace(MediaConfig(), phash_index_path=None)
    dataset = build_dataset(real_dir, fake_dir, config, seed=seed, calibration_fraction=calibration_fraction)
    models = models or [(DEFAULT_MODEL_ID, DEFAULT_MODEL_REVISION)]
    results = []
    for model_id, revision in models:
        print(f"Scoring {len(dataset.items)} images with {model_id}", file=sys.stderr, flush=True)
        model_config = replace(config, model_id=model_id, model_revision=revision)
        results.append(_model_result(model_id, revision, classifier_factory(model_config), dataset.items, model_config))

    counts = Counter((item.label, item.category) for item in dataset.items)
    splits = Counter((item.label, item.split) for item in dataset.items)
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "notice": NOTICE,
        "sources": list(sources),
        "settings": {
            "seed": seed,
            "calibration_fraction": calibration_fraction,
            "elevated_score": config.elevated_score,
            "low_score": config.low_score,
        },
        "dataset": {
            REAL: sum(item.label == REAL for item in dataset.items),
            FAKE: sum(item.label == FAKE for item in dataset.items),
            "by_category": {f"{label}/{category}": count for (label, category), count in sorted(counts.items())},
            "by_split": {f"{label}/{split}": count for (label, split), count in sorted(splits.items())},
            "duplicates_removed": dataset.duplicates_removed,
            "same_file_under_both_labels": dataset.label_conflicts,
            "unreadable_files": dataset.unreadable,
            "skipped_other_types": dataset.skipped_other_types,
        },
        "models": results,
        "limitations": list(LIMITATIONS),
    }


def write_result(result: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
