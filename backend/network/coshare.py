"""Time-window co-share detection between pairs of accounts."""

import re
import statistics
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import networkx as nx

from backend.network.config import CoordinationConfig
from backend.network.dataset import Post

SIGNALS = ("url", "media", "text")

_URL_PATTERN = re.compile(r"https?://\S+")


def _normalize_character(character: str) -> str:
    category = unicodedata.category(character)
    # Letters, numbers and combining marks stay: Indic vowels are marks, so removing
    # them would make पानी and पीना look identical.
    if category[0] in "LMN":
        return character
    # Format characters such as zero-width joiners sit inside words.
    return "" if category == "Cf" else " "


def normalize_text(text: str) -> str:
    """Remove the case, punctuation and link differences used to disguise copies."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    without_urls = _URL_PATTERN.sub(" ", folded)
    return " ".join("".join(map(_normalize_character, without_urls)).split())


def normalize_url(url: str) -> str | None:
    """Make one link compare equal regardless of tracking parameters or fragments.

    Returns None for text that isn't a usable link, which then gives no signal.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if not parts.netloc:
        return None
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
    normalized_url = normalize_url(post.url) if post.url else None
    if normalized_url:
        yield "url", normalized_url
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
    # The matched (signal, value) keys on each post, which show which keys are one item.
    keys_by_post: dict[str, set[tuple[str, str]]] = field(default_factory=lambda: defaultdict(set))

    @property
    def distinct_items(self) -> int:
        # Keys carried by the same post are one item, so a post matching on URL, media
        # and text counts once. Separate posts matching on different signals are separate
        # items. Two different links stay two items even if a shared logo connects them.
        linked = nx.Graph()
        for keys in self.keys_by_post.values():
            linked.add_nodes_from(keys)
            nx.add_path(linked, sorted(keys))
        return max(nx.number_connected_components(linked), *(len(values) for values in self.items.values()))

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
                pair.keys_by_post[earlier.id].add((signal, value))
                pair.keys_by_post[later.id].add((signal, value))
                pair.delays[(earlier.id, later.id)] = delay
                pair.platforms.update(post.platform for post in (earlier, later) if post.platform)
                pair.first_seen_at = min(pair.first_seen_at, later.created_at)
    return pairs
