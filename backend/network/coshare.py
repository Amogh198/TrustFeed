"""Time-window co-share detection between pairs of accounts."""

import re
import statistics
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.network.config import CoordinationConfig
from backend.network.dataset import Post

SIGNALS = ("url", "media", "text")

_URL_PATTERN = re.compile(r"https?://\S+")
_NON_WORD_PATTERN = re.compile(r"[^\w\s]")


def normalize_text(text: str) -> str:
    """Remove the case, punctuation and link differences used to disguise copies."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    without_urls = _URL_PATTERN.sub(" ", folded)
    return " ".join(_NON_WORD_PATTERN.sub(" ", without_urls).split())


def normalize_url(url: str) -> str:
    """Make one link compare equal regardless of tracking parameters or fragments."""
    parts = urlsplit(url.strip())
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    )
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), "")
    )


def post_signals(post: Post, config: CoordinationConfig) -> Iterator[tuple[str, str]]:
    """Yield every (signal, value) that can link this post to another account's post."""
    if post.url:
        yield "url", normalize_url(post.url)
    if post.media_hash:
        yield "media", post.media_hash.lower()
    normalized = normalize_text(post.text)
    if len(normalized) >= config.min_text_length:
        yield "text", normalized


@dataclass
class CoShare:
    """Everything two accounts were observed sharing within the time window."""

    source: str
    target: str
    first_seen_at: datetime
    items: dict[str, set[str]] = field(default_factory=lambda: {signal: set() for signal in SIGNALS})
    # One post pair can match on several signals, so it is keyed to count its delay once.
    delays: dict[tuple[str, str], float] = field(default_factory=dict)
    platforms: set[str] = field(default_factory=set)

    @property
    def distinct_items(self) -> int:
        # One post usually matches on URL, media and text together. Taking the
        # maximum, not the sum, stops that being counted as three items.
        return max(len(values) for values in self.items.values())

    @property
    def signal_counts(self) -> dict[str, int]:
        return {signal: len(self.items[signal]) for signal in SIGNALS}

    @property
    def min_delay(self) -> float:
        return min(self.delays.values())

    @property
    def median_delay(self) -> float:
        return statistics.median(self.delays.values())

    def item_keys(self) -> set[tuple[str, str]]:
        return {(signal, value) for signal, values in self.items.items() for value in values}


def find_co_shares(
    posts: Iterable[Post], config: CoordinationConfig
) -> dict[tuple[str, str], CoShare]:
    """Find account pairs that posted the same item within ``window_seconds``.

    The window is inclusive. Repeat posts by one account never form a pair.
    """
    posts_by_signal: dict[tuple[str, str], list[Post]] = defaultdict(list)
    ordered = sorted(posts, key=lambda post: (post.created_at, post.id))
    for post in ordered:
        for signal in post_signals(post, config):
            posts_by_signal[signal].append(post)

    pairs: dict[tuple[str, str], CoShare] = {}
    for (signal, value), group in sorted(posts_by_signal.items()):
        for index, earlier in enumerate(group):
            for later in group[index + 1 :]:
                delay = (later.created_at - earlier.created_at).total_seconds()
                if delay > config.window_seconds:
                    break  # The group is time-sorted, so no later post can match.
                if earlier.account_id == later.account_id:
                    continue
                source, target = sorted((earlier.account_id, later.account_id))
                pair = pairs.get((source, target))
                if pair is None:
                    pair = CoShare(source, target, later.created_at)
                    pairs[(source, target)] = pair
                pair.items[signal].add(value)
                pair.delays[(earlier.id, later.id)] = delay
                pair.platforms.update(post.platform for post in (earlier, later) if post.platform)
                pair.first_seen_at = min(pair.first_seen_at, later.created_at)
    return pairs
