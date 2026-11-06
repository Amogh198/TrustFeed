"""Image fingerprints: short values that stay similar when an image is lightly changed.

A fingerprint is not a signature. It can't show who made a file or that it is unchanged. SHA-256 only
shows that two files are byte-for-byte the same. Only hashes are stored here, never the upload.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from backend.media.errors import HashIndexUnavailable
from backend.media.models import FingerprintMatch, MediaAnalysisResult
from backend.media.phash import ReferenceEntry, hamming_distance

# Each one notices a different thing: overall structure, gradients, wavelet detail and colour.
HASH_KINDS = ("phash", "dhash", "whash", "colorhash")
# Chosen on the calibration split of data/eval/fingerprints_2026-11-05.json, where unrelated images
# matched on any one of these no more than 0.1% of the time. Colour hash met that target at no distance,
# so it is reported but never decides a match.
MATCH_LIMITS = {"phash": 17, "dhash": 16, "whash": 7}
MATCHES_NEEDED = 2
# A flat picture has almost no gradient, so its fingerprints say nothing about which picture it is.
_MIN_DHASH_BITS = 3
EXACT_COPY = "exact_copy"
LIKELY_SAME_IMAGE = "likely_same_image"
_store_lock = threading.Lock()


def compute_fingerprints(image) -> dict[str, str]:
    """Return every perceptual hash of an image. The image is not kept."""
    import imagehash

    rgb = image.convert("RGB")
    return {
        "phash": str(imagehash.phash(rgb)),
        "dhash": str(imagehash.dhash(rgb)),
        "whash": str(imagehash.whash(rgb)),
        "colorhash": str(imagehash.colorhash(rgb)),
    }


def fingerprint_distances(left: dict[str, str], right: dict[str, str]) -> dict[str, int]:
    """Distance for each kind both sides have. Values of different lengths can't be compared."""
    distances = {}
    for kind in HASH_KINDS:
        first, second = left.get(kind), right.get(kind)
        if first and second and len(first) == len(second):
            distances[kind] = hamming_distance(first, second)
    return distances


def is_informative(hashes: dict[str, str]) -> bool:
    dhash = hashes.get("dhash")
    return bool(dhash) and int(dhash, 16).bit_count() >= _MIN_DHASH_BITS


def looks_like_same_image(distances: dict[str, int]) -> bool:
    agreeing = sum(1 for kind, limit in MATCH_LIMITS.items() if kind in distances and distances[kind] <= limit)
    return agreeing >= MATCHES_NEEDED


def same_picture(left: dict[str, str], right: dict[str, str]) -> bool:
    """The rule for two sets of hashes: both have detail, and enough kinds agree."""
    return is_informative(left) and is_informative(right) and looks_like_same_image(fingerprint_distances(left, right))


def entry_hashes(entry: ReferenceEntry) -> dict[str, str]:
    return {kind: value for kind in HASH_KINDS if (value := getattr(entry, kind, None))}


class CaseFingerprint(BaseModel):
    """What is kept from an earlier case: hashes and a date, never the image or its file name."""

    case_id: str
    seen_at: str
    sha256: str | None = None
    frames: list[dict[str, str]] = Field(default_factory=list)
    local_features: list[str] = Field(default_factory=list)


class CaseFingerprintStore:
    """Earlier cases' hashes in a JSON file, compared by linear scan."""

    def __init__(self, entries: list[CaseFingerprint] | None = None, skipped: int = 0) -> None:
        self.entries = entries or []
        self.skipped = skipped

    @classmethod
    def load(cls, path: Path) -> CaseFingerprintStore:
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HashIndexUnavailable("The earlier-case fingerprint store could not be read.") from exc
        raw = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            raise HashIndexUnavailable("The earlier-case fingerprint store has an invalid format.")
        entries: list[CaseFingerprint] = []
        skipped = 0
        for item in raw:
            try:
                entries.append(CaseFingerprint.model_validate(item))
            except ValueError:
                skipped += 1
        return cls(entries, skipped)

    def __len__(self) -> int:
        return len(self.entries)

    def add(self, entry: CaseFingerprint) -> None:
        self.entries = [existing for existing in self.entries if existing.case_id != entry.case_id] + [entry]

    def remove(self, case_id: str) -> bool:
        kept = [entry for entry in self.entries if entry.case_id != case_id]
        removed = len(kept) != len(self.entries)
        self.entries = kept
        return removed

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        # This file only ever holds hashes and a date. Local features are saved with the case.
        document = {"version": 1, "entries": [entry.model_dump(exclude={"local_features"}) for entry in self.entries]}
        temporary.write_text(json.dumps(document) + "\n", encoding="utf-8")
        os.replace(temporary, path)


def fingerprint_record(result: MediaAnalysisResult, case_id: str, seen_at: str) -> CaseFingerprint | None:
    """What is kept from a case for later comparison, or None if there is nothing to keep."""
    check = result.checks.fingerprint
    if check is None:
        return None
    frames = [frame.fingerprints for frame in result.checks.keyframes.frames if frame.fingerprints]
    if check.hashes:
        frames = [check.hashes, *frames]
    sha256 = check.sha256 or result.sha256
    if not sha256 and not frames:
        return None
    return CaseFingerprint(case_id=case_id, seen_at=seen_at, sha256=sha256, frames=frames, local_features=check.local_features)


def remember_fingerprints(
    result: MediaAnalysisResult, case_id: str, path: Path, *, seen_at: str | None = None
) -> bool:
    """Keep a case's hashes for later comparison. Returns False if there is nothing to keep."""
    moment = seen_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    record = fingerprint_record(result, case_id, moment)
    if record is None:
        return False
    with _store_lock:
        store = CaseFingerprintStore.load(path)
        store.add(record)
        store.save(path)
    return True


@dataclass(frozen=True)
class QueryFrame:
    timestamp_s: float | None
    hashes: dict[str, str]


def _best_visual(
    frames: Sequence[QueryFrame], targets: Iterable[dict[str, str]]
) -> tuple[dict[str, int], float | None] | None:
    best: tuple[int, dict[str, int], float | None] | None = None
    usable_targets = [target for target in targets if is_informative(target)]
    for frame in frames:
        if not is_informative(frame.hashes):
            continue
        for target in usable_targets:
            distances = fingerprint_distances(frame.hashes, target)
            if looks_like_same_image(distances):
                total = sum(distances[kind] for kind in MATCH_LIMITS if kind in distances)
                if best is None or total < best[0]:
                    best = (total, distances, frame.timestamp_s)
    return (best[1], best[2]) if best else None


def _sort_key(match: FingerprintMatch) -> tuple[int, int]:
    return (0 if match.kind == EXACT_COPY else 1, sum(match.distances.values()))


def find_matches(
    sha256: str | None,
    frames: Sequence[QueryFrame],
    references: Iterable[ReferenceEntry],
    cases: Iterable[CaseFingerprint],
) -> list[FingerprintMatch]:
    """Compare against references and earlier cases. An exact file copy outranks a visual match."""
    matches = []
    for entry in references:
        details = {"label": entry.label, "first_seen": entry.first_seen, "source": entry.source}
        if sha256 and entry.sha256 == sha256:
            matches.append(FingerprintMatch(kind=EXACT_COPY, found_in="reference", **details))
        elif visual := _best_visual(frames, [entry_hashes(entry)]):
            distances, timestamp = visual
            matches.append(
                FingerprintMatch(
                    kind=LIKELY_SAME_IMAGE, found_in="reference", distances=distances, timestamp_s=timestamp, **details
                )
            )
    for case in cases:
        details = {"case_id": case.case_id, "first_seen": case.seen_at}
        if sha256 and case.sha256 == sha256:
            matches.append(FingerprintMatch(kind=EXACT_COPY, found_in="earlier_case", **details))
        elif visual := _best_visual(frames, case.frames):
            distances, timestamp = visual
            matches.append(
                FingerprintMatch(
                    kind=LIKELY_SAME_IMAGE, found_in="earlier_case", distances=distances, timestamp_s=timestamp, **details
                )
            )
    return sorted(matches, key=_sort_key)
