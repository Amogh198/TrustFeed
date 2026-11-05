"""Adapters that read public posts from real platforms into one shape."""

from backend.network.sources.base import (
    Fetch,
    FetchError,
    PublicPost,
    SearchOutcome,
    SearchQuery,
    Source,
)
from backend.network.sources.bluesky import BlueskySource
from backend.network.sources.fetching import (
    Budgeted,
    RecordingFetch,
    ReplayFetch,
    live_fetch,
)
from backend.network.sources.hackernews import HackerNewsSource
from backend.network.sources.lemmy import LemmySource
from backend.network.sources.mastodon import MastodonSource


def default_sources() -> list[Source]:
    return [MastodonSource(), LemmySource(), HackerNewsSource(), BlueskySource()]


# What was found when each platform was tried without a login on 2026-11-05. It's
# reported with every trace, so nobody takes silence from these platforms as evidence.
NOT_CONNECTED = {
    "reddit": "Search returned HTTP 403 without a registered app, so it needs API credentials.",
    "youtube": "The Data API returned HTTP 403 without an API key.",
    "x": "Not tried. Its API needs paid access, which the team doesn't have.",
    "private channels": "WhatsApp, Telegram private groups and closed groups can't be seen by any public API.",
}

__all__ = [
    "NOT_CONNECTED",
    "BlueskySource",
    "Budgeted",
    "Fetch",
    "FetchError",
    "HackerNewsSource",
    "LemmySource",
    "MastodonSource",
    "PublicPost",
    "RecordingFetch",
    "ReplayFetch",
    "SearchOutcome",
    "SearchQuery",
    "Source",
    "default_sources",
    "live_fetch",
]
