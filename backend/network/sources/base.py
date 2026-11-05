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


Fetch = Callable[[str], Any]


@dataclass(frozen=True)
class SearchQuery:
    urls: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()
    hashtags: tuple[str, ...] = ()

    @classmethod
    def from_submission(
        cls,
        text: str | None = None,
        url: str | None = None,
        urls: tuple[str, ...] = (),
        hashtags: tuple[str, ...] = (),
    ) -> "SearchQuery":
        """Build a search from submitted content. Long text becomes one leading phrase."""
        text = text or ""
        found_urls = [*urls, *([url] if url else []), *URL_IN_TEXT.findall(text)]
        found_tags = [*hashtags, *_HASHTAG_IN_TEXT.findall(text)]
        words = normalize_text(text).split()
        phrase = " ".join(words[:_MAX_PHRASE_WORDS])
        return cls(
            urls=tuple(dict.fromkeys(found_urls)),
            phrases=(phrase,) if len(phrase) >= _MIN_PHRASE_LENGTH else (),
            hashtags=tuple(dict.fromkeys(tag.lstrip("#").casefold() for tag in found_tags if tag.lstrip("#"))),
        )

    def is_empty(self) -> bool:
        return not (self.urls or self.phrases or self.hashtags)


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
    hashtags: tuple[str, ...] = ()
    # (account id, handle) of each mentioned account.
    mentions: tuple[tuple[str, str], ...] = ()
    followers: int = 0

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


def safe_web_link(link: str | None) -> str | None:
    """Return the link only if it's http or https, as a page may render it as a link."""
    if not link:
        return None
    try:
        scheme = urlsplit(link.strip()).scheme.lower()
    except ValueError:
        return None
    return link if scheme in ("http", "https") else None


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
