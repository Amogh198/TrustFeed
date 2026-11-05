"""Perceptual hashing and provenance lookup.

Lookups go through the small ``HashIndex`` protocol, so a database-backed store
can replace the JSON file later without changing the analyzer.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from backend.media.errors import HashIndexUnavailable
from backend.media.models import HashMatch

_PHASH_RE = re.compile(r"^[0-9a-f]{16}$")


def compute_phash(image) -> str:
    import imagehash

    return str(imagehash.phash(image))


def hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


class ReferenceEntry(BaseModel):
    phash: str
    label: str
    first_seen: str | None = None
    source: str | None = None
    # Older index files have only phash, so these stay optional.
    sha256: str | None = None
    dhash: str | None = None
    whash: str | None = None
    colorhash: str | None = None


class HashIndex(Protocol):
    def __len__(self) -> int: ...

    def lookup(self, phash: str, max_distance: int) -> list[HashMatch]: ...


class JsonHashIndex:
    """Reference hashes stored in a JSON file, compared by linear scan."""

    def __init__(self, entries: list[ReferenceEntry] | None = None, skipped: int = 0) -> None:
        self.entries = entries or []
        self.skipped = skipped

    @classmethod
    def load(cls, path: Path) -> JsonHashIndex:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HashIndexUnavailable("The pHash reference index could not be read.") from exc
        raw = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            raise HashIndexUnavailable("The pHash reference index has an invalid format.")
        entries: list[ReferenceEntry] = []
        skipped = 0
        for item in raw:
            try:
                entry = ReferenceEntry.model_validate(item)
            except ValueError:
                skipped += 1
                continue
            if _PHASH_RE.match(entry.phash):
                entries.append(entry)
            else:
                skipped += 1
        return cls(entries, skipped)

    def __len__(self) -> int:
        return len(self.entries)

    def lookup(self, phash: str, max_distance: int) -> list[HashMatch]:
        matches = []
        for entry in self.entries:
            distance = hamming_distance(phash, entry.phash)
            if distance <= max_distance:
                matches.append(
                    HashMatch(
                        phash=entry.phash,
                        distance=distance,
                        label=entry.label,
                        first_seen=entry.first_seen,
                        source=entry.source,
                    )
                )
        return sorted(matches, key=lambda match: match.distance)

    def add(self, entry: ReferenceEntry) -> None:
        self.entries.append(entry)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        document = {"version": 1, "entries": [entry.model_dump() for entry in self.entries]}
        temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
