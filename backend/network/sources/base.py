"""Shared types for reading public posts from social platforms."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urlsplit

from backend.network.coshare import normalize_text

# Text shorter than this, once normalized, is too generic to search for.
_MIN_PHRASE_LENGTH = 20
_MAX_PHRASE_WORDS = 12
URL_IN_TEXT = re.compile(r"https?://[^\s<>\"']+")
_HASHTAG_IN_TEXT = re.compile(r"(?<![^\s(])#([^\s#.,;:!?()]+)")


class FetchError(Exception):
    """A platform couldn't be read. The message says why and is safe to show to users."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


Fetch = Callable[[str], Any]


@dataclass(frozen=True)
class SearchQuery:
    # Links the user submitted or is watching.
    urls: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()
    hashtags: tuple[str, ...] = ()
    # Pages where a source search found the image. A post linking to one of these may be
    # about something else on that page, so these matches are reported separately.
    page_urls: tuple[str, ...] = ()

    @classmethod
    def from_submission(
        cls,
        text: str | None = None,
        url: str | None = None,
        urls: tuple[str, ...] = (),
        hashtags: tuple[str, ...] = (),
        watched_urls: tuple[str, ...] = (),
    ) -> "SearchQuery":
        """Build a search from submitted content. Long text becomes one leading phrase.

        ``urls`` are page links from a source search. ``watched_urls`` count as submitted.
        """
        text = text or ""
        candidates: list[str] = [*watched_urls, *([url] if url else []), *URL_IN_TEXT.findall(text)]
        found_urls = tuple(dict.fromkeys(candidates))
        found_tags = [*hashtags, *_HASHTAG_IN_TEXT.findall(text)]
        words = normalize_text(text).split()
        phrase = " ".join(words[:_MAX_PHRASE_WORDS])
        return cls(
            urls=found_urls,
            page_urls=tuple(link for link in dict.fromkeys(urls) if link not in found_urls),
            phrases=(phrase,) if len(phrase) >= _MIN_PHRASE_LENGTH else (),
            hashtags=tuple(dict.fromkeys(tag.lstrip("#").casefold() for tag in found_tags if tag.lstrip("#"))),
        )

    @property
    def all_urls(self) -> tuple[str, ...]:
        return (*self.urls, *self.page_urls)

    def is_empty(self) -> bool:
        return not (self.all_urls or self.phrases or self.hashtags)


@dataclass(frozen=True)
class PublicPost:
    """One public post, in the same shape for every platform."""

    platform: str
    id: str
    author_id: str
    author_handle: str
    # What the platform's API needs in order to list this author's other posts.
    author_ref: str
    created_at: str
    permalink: str | None = None
    text: str = ""
    url: str | None = None
    # Further links in the post. They count when matching but aren't co-share signals.
    other_links: tuple[str, ...] = ()
    hashtags: tuple[str, ...] = ()
    # (account id, handle) of each mentioned account.
    mentions: tuple[tuple[str, str], ...] = ()
    followers: int = 0
    # How many times it was reposted. Platforms don't say when, so this can't order events.
    repost_count: int | None = None
    # Public thumbnails on this post. They're untrusted, so they're only read through the protected client.
    image_urls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Platform responses are untrusted. A wrong type here counts as one malformed
        # record, rather than stopping the whole trace later on.
        for name in ("id", "author_id", "author_handle", "author_ref", "created_at", "text"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"Post field {name} must be text")  # noqa: TRY004
        for name in ("permalink", "url"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"Post field {name} must be text")


@dataclass
class SearchOutcome:
    posts: list[PublicPost] = field(default_factory=list)
    searches_run: int = 0
    # Why a search failed, or why a kind of search doesn't exist on this platform.
    failures: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    # Records the platform returned that couldn't be understood, and were left out.
    malformed: int = 0


class Source(Protocol):
    platform: str
    label: str

    def search(self, query: SearchQuery, fetch: Fetch) -> SearchOutcome: ...

    def author_posts(self, post: PublicPost, fetch: Fetch) -> list[PublicPost]: ...


def count_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def safe_web_link(link: str | None) -> str | None:
    """Return the link only if it's http or https, as a page may render it as a link."""
    if not link:
        return None
    try:
        scheme = urlsplit(link.strip()).scheme.lower()
    except ValueError:
        return None
    return link if scheme in ("http", "https") else None


def text_links(*values: Any) -> tuple[str, ...]:
    """Keep the values that are text. A picture link of the wrong type shouldn't cost the whole post."""
    return tuple(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def utc_timestamp(value: Any) -> str:
    """Return a timezone-aware ISO timestamp. Lemmy can omit the zone, which means UTC."""
    if not isinstance(value, str):
        raise ValueError(f"Not a timestamp: {value!r}")  # noqa: TRY004
    parsed = datetime.fromisoformat(value)
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).isoformat()


class _HtmlText(HTMLParser):
    """Read post HTML, keeping visible text and links but not the text of links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("br", "p"):
            self.parts.append(" ")
        if tag != "a":
            return
        values = dict(attrs)
        classes = values.get("class") or ""
        if "mention" in classes or "hashtag" in classes:
            return
        if values.get("href"):
            self.links.append(values["href"] or "")
        self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def read_html(content: str) -> tuple[str, list[str]]:
    """Return the visible text of post HTML, and the links in it."""
    parser = _HtmlText()
    parser.feed(content)
    return " ".join("".join(parser.parts).split()), parser.links
