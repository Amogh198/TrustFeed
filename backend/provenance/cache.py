"""Saves search results by the file's SHA-256, so searching the same file again spends no credits.

Files hold what a provider returned for a hash: web addresses, titles and dates. They never hold the image or a key.
What's read back is treated as untrusted, the same as a fresh response. Keep the folder private and out of Git,
because a saved result shows that someone searched for that file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.provenance.classify import clean_text, clean_url
from backend.provenance.models import MatchType
from backend.provenance.providers import Candidate

logger = logging.getLogger(__name__)

_VERSION = 1


def _to_row(candidate: Candidate) -> dict[str, object]:
    return {
        "provider": candidate.provider,
        "match_type": candidate.match_type.value,
        "page_url": candidate.page_url,
        "page_title": candidate.page_title,
        "image_url": candidate.image_url,
        "crawl_date": candidate.crawl_date.isoformat() if candidate.crawl_date else None,
        "provider_date_text": candidate.provider_date_text,
        "decide_type_by_phash": candidate.decide_type_by_phash,
    }


def _from_row(row: dict) -> Candidate:
    crawl = row.get("crawl_date")
    return Candidate(
        provider=str(row["provider"]),
        match_type=MatchType(row["match_type"]),
        page_url=clean_url(row.get("page_url")),
        page_title=clean_text(row.get("page_title")),
        image_url=clean_url(row.get("image_url")),
        crawl_date=datetime.fromisoformat(crawl) if isinstance(crawl, str) else None,
        provider_date_text=clean_text(row.get("provider_date_text"), limit=40),
        decide_type_by_phash=row.get("decide_type_by_phash") is True,
    )


class ResultsCache:
    def __init__(self, folder: Path, max_age_days: float) -> None:
        self._folder = folder
        self._max_age = timedelta(days=max_age_days)

    def _path(self, media_sha256: str, provider_key: str) -> Path:
        name = hashlib.sha256(f"{_VERSION}:{media_sha256}:{provider_key}".encode()).hexdigest()
        return self._folder / f"{name}.json"

    def get(self, media_sha256: str, provider_key: str) -> tuple[list[Candidate], datetime] | None:
        """Return the saved results and when they were saved. Anything old or unreadable counts as not saved."""
        try:
            document = json.loads(self._path(media_sha256, provider_key).read_text(encoding="utf-8"))
            saved_at = datetime.fromisoformat(document["saved_at"])
            if datetime.now(timezone.utc) - saved_at > self._max_age:
                return None
            return [_from_row(row) for row in document["candidates"]], saved_at
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
            logger.warning("A saved search result could not be read: %s", type(exc).__name__)
            return None

    def put(self, media_sha256: str, provider_key: str, candidates: list[Candidate]) -> None:
        """Failing to save only means a later search isn't saved from spending."""
        path = self._path(media_sha256, provider_key)
        temporary = path.with_suffix(".tmp")
        document = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "candidates": [_to_row(candidate) for candidate in candidates],
        }
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(document), encoding="utf-8")
            os.replace(temporary, path)
        except OSError as exc:
            logger.warning("A search result could not be saved: %s", type(exc).__name__)
