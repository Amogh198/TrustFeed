"""Read a publication date from a web page. Page content is untrusted and only ever parsed."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from backend.provenance.classify import clean_text

_EARLIEST_PLAUSIBLE = datetime(1990, 1, 1, tzinfo=timezone.utc)
_ARTICLE_META = {"article:published_time", "og:article:published_time"}
_NEWS_TYPES = {"newsarticle", "reportagenewsarticle", "analysisnewsarticle", "opinionnewsarticle"}
_MAX_JSON_DEPTH = 12


@dataclass(frozen=True)
class PageDate:
    observed_at: datetime
    evidence: str


@dataclass(frozen=True)
class PageFacts:
    date: PageDate | None = None
    title: str | None = None
    is_news_article: bool = False


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_blocks: list[str] = []
        self.article_times: list[str] = []
        self.title_parts: list[str] = []
        self._capture: str | None = None

    def handle_starttag(self, tag, attrs) -> None:
        values = {name.lower(): value for name, value in attrs if value is not None}
        if tag == "script" and values.get("type", "").split(";")[0].strip().lower() == "application/ld+json":
            self._capture = "json"
            self.json_blocks.append("")
        elif tag == "title" and not self.title_parts:
            self._capture = "title"
        elif tag == "meta":
            name = (values.get("property") or values.get("name") or "").lower()
            if name in _ARTICLE_META and values.get("content"):
                self.article_times.append(values["content"])

    def handle_endtag(self, tag) -> None:
        if tag in {"script", "title"}:
            self._capture = None

    def handle_data(self, data) -> None:
        if self._capture == "json":
            self.json_blocks[-1] += data
        elif self._capture == "title":
            self.title_parts.append(data)


def parse_date(value: object) -> tuple[datetime, bool, bool] | None:
    """Return ``(utc_time, date_only, had_zone)``, or None if unusable or implausible."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not 8 <= len(text) <= 40:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    date_only = len(text) <= 10
    had_zone = parsed.tzinfo is not None
    moment = parsed.astimezone(timezone.utc) if had_zone else parsed.replace(tzinfo=timezone.utc)
    if not _EARLIEST_PLAUSIBLE <= moment <= datetime.now(timezone.utc) + timedelta(days=1):
        return None
    return moment, date_only, had_zone


def _note(base: str, date_only: bool, had_zone: bool) -> str:
    if date_only:
        return f"{base} (date only, no time given)."
    if not had_zone:
        return f"{base} (no time zone given, read as UTC)."
    return f"{base}."


def _walk(node: object, depth: int = 0) -> Iterator[dict]:
    if depth > _MAX_JSON_DEPTH:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value, depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, depth + 1)


def _types(node: dict) -> set[str]:
    kinds = node.get("@type")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    return {kind.lower() for kind in kinds if isinstance(kind, str)}


def _read_json_ld(blocks: list[str]) -> tuple[PageDate | None, bool]:
    best: PageDate | None = None
    best_rank = -1
    is_news = False
    for block in blocks:
        try:
            document = json.loads(block)
        except (ValueError, RecursionError):
            continue
        for node in _walk(document):
            kinds = _types(node)
            is_news = is_news or bool(kinds & _NEWS_TYPES)
            parsed = parse_date(node.get("datePublished"))
            if parsed is None:
                continue
            # Prefer the page's own article over dates on nested objects such as comments.
            rank = 1 if any(kind.endswith(("article", "posting", "webpage")) for kind in kinds) else 0
            if rank > best_rank:
                best_rank = rank
                best = PageDate(parsed[0], _note("JSON-LD datePublished on the page", parsed[1], parsed[2]))
    return best, is_news


def _read_last_modified(headers: Mapping[str, str]) -> PageDate | None:
    raw = headers.get("last-modified")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    moment = parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if not _EARLIEST_PLAUSIBLE <= moment <= datetime.now(timezone.utc) + timedelta(days=1):
        return None
    return PageDate(moment, "HTTP Last-Modified header, the weakest hint: it may only show when the page last changed.")


def read_page_facts(headers: Mapping[str, str], body: bytes) -> PageFacts:
    """Use JSON-LD datePublished, then article:published_time, then Last-Modified."""
    content_type = headers.get("content-type", "").lower()
    if "html" not in content_type and "xml" not in content_type:
        return PageFacts(date=_read_last_modified(headers))

    parser = _PageParser()
    try:
        parser.feed(body.decode("utf-8", "replace"))
        parser.close()
    except (AssertionError, RecursionError, ValueError):
        return PageFacts(date=_read_last_modified(headers))

    date, is_news = _read_json_ld(parser.json_blocks)
    if date is None:
        for raw in parser.article_times:
            parsed = parse_date(raw)
            if parsed:
                date = PageDate(parsed[0], _note("Open Graph article:published_time on the page", parsed[1], parsed[2]))
                break
    return PageFacts(
        date=date or _read_last_modified(headers),
        title=clean_text("".join(parser.title_parts)),
        is_news_article=is_news,
    )
