"""The linked demo story: one invented rumour, traced through the real pipeline offline.

The same adapters, matching, history reads and engine run as for a live trace. The
only difference is that responses come from a labelled synthetic recording, and the
platforms carry invented names so nothing implies a real service hosted these posts.
"""

import json
from functools import lru_cache
from typing import Any

from backend.network.config import CoordinationConfig
from backend.network.coshare import normalize_text, normalize_url
from backend.network.dataset import DEMO_STORY_PATH
from backend.network.sources import (
    HackerNewsSource,
    LemmySource,
    MastodonSource,
    ReplayFetch,
    Source,
)
from backend.network.trace import TraceResult, trace_public_spread

DEMO_STORY_CASE_ID = "demo-story-001"


def story_sources() -> list[Source]:
    return [
        MastodonSource("story-social.example", "demo_microblog", "Demo microblog (synthetic)"),
        LemmySource("story-lemmy.example", "demo_forum", "Demo forum (synthetic)"),
        HackerNewsSource("demo_news", "Demo news board (synthetic)"),
    ]


@lru_cache(maxsize=1)
def _story_document() -> dict[str, Any]:
    with DEMO_STORY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def get_demo_story() -> dict[str, Any]:
    """Return the sample a presenter submits, and the notice to show with it."""
    document = _story_document()
    return {
        "case_id": DEMO_STORY_CASE_ID,
        "synthetic": True,
        "notice": document["notice"],
        "submission": dict(document["submission"]),
    }


def is_demo_story(text: str | None = None, url: str | None = None) -> bool:
    """True only for the story's exact link or text, so real content never gets its data."""
    submission = _story_document()["submission"]
    same_url = bool(url) and normalize_url(url or "") == normalize_url(submission["url"])
    same_text = bool(text) and normalize_text(text or "") == normalize_text(submission["text"])
    return same_url or same_text


def trace_demo_story(case_id: str = DEMO_STORY_CASE_ID, config: CoordinationConfig | None = None) -> TraceResult:
    return trace_public_spread(
        case_id,
        **_story_document()["submission"],
        sources=story_sources(),
        fetch=ReplayFetch(DEMO_STORY_PATH),
        config=config,
    )
