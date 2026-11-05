"""Search public sources for evidence about a claim.

Everything these services return is untrusted data. It is compared and quoted,
never followed as an instruction. Every request goes through the provenance lane's
safe requester, and a missing key or failed service is reported, not hidden.
This module is only reached when a request sets ``search_web``.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

from backend.provenance.safe_http import (
    HttpBlocked,
    HttpFailed,
    HttpResponse,
    safe_request,
)

Request = Callable[..., HttpResponse]

# A generic client name, with nothing that identifies a user.
_HEADERS = {"User-Agent": "TrustFeed/0.1 (claim evidence search)", "Accept": "application/json"}
_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_PAGE_BYTES = 1024 * 1024
_MAX_DOCUMENT_CHARS = 20_000
_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
_GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_FACT_CHECK_API = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
_SKIPPED_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg"}


@dataclass(frozen=True)
class Document:
    provider: str
    title: str
    url: str
    domain: str
    text: str
    date: str | None = None
    # What the date means: last_edited, first_seen, reviewed or none. It is not always publication.
    date_kind: str = "none"
    # Fact-check reviews only: the publisher's own words, and the claim they reviewed.
    rating: str | None = None
    reviewed_claim: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    name: str
    status: str
    reason: str | None = None
    documents: list[Document] = field(default_factory=list)


class Provider(Protocol):
    name: str

    def search(self, query: str, deadline: float) -> ProviderResult: ...


def _domain(url: str) -> str:
    return (urlsplit(url).hostname or "").casefold().removeprefix("www.")


def _public_https(value: object) -> str | None:
    """Keep only links that are safe to show as a link. A service's response is not trusted."""
    return value if isinstance(value, str) and value.startswith("https://") and _domain(value) else None


def _get_json(request: Request, url: str, deadline: float) -> Any:
    response = request(url, headers=_HEADERS, deadline=deadline, max_bytes=_MAX_JSON_BYTES, timeout_s=8.0)
    if response.status != 200:
        raise _Refused(response.status)
    return json.loads(response.body.decode("utf-8"))


class _Refused(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


def _failure_reason(name: str, error: Exception) -> str:
    """Say what went wrong without any URL, because some hold a key or the query."""
    if isinstance(error, _Refused):
        return f"{name} refused the request (HTTP {error.status})."
    if isinstance(error, HttpFailed):
        return f"{name} could not be read ({error.kind})."
    if isinstance(error, HttpBlocked):
        return f"{name} was blocked by the safety rules."
    return f"{name} returned something unreadable."


_FAILURES = (_Refused, HttpFailed, HttpBlocked, ValueError, KeyError, TypeError, AttributeError)


class WikipediaProvider:
    name = "wikipedia"

    def __init__(self, request: Request = safe_request, max_pages: int = 3) -> None:
        self._request = request
        self._max_pages = max_pages

    def _page(self, title: str, deadline: float) -> Document | None:
        params = {
            "action": "query", "format": "json", "formatversion": "2", "prop": "extracts|info", "inprop": "url",
            "explaintext": "1", "redirects": "1", "titles": title,
        }
        pages = _get_json(self._request, f"{_WIKIPEDIA_API}?{urlencode(params)}", deadline)["query"]["pages"]
        page = pages[0]
        url = _public_https(page.get("fullurl"))
        text = page.get("extract")
        if not url or not isinstance(text, str) or not text.strip():
            return None
        return Document(
            self.name, str(page.get("title") or title), url, _domain(url), text[:_MAX_DOCUMENT_CHARS],
            date=page.get("touched"), date_kind="last_edited",
        )

    def search(self, query: str, deadline: float) -> ProviderResult:
        params = {
            "action": "query", "format": "json", "formatversion": "2", "list": "search",
            "srsearch": query, "srlimit": str(self._max_pages),
        }
        try:
            found = _get_json(self._request, f"{_WIKIPEDIA_API}?{urlencode(params)}", deadline)["query"]["search"]
            pages = [self._page(str(item["title"]), deadline) for item in found[: self._max_pages]]
        except _FAILURES as error:
            return ProviderResult(self.name, "unavailable", _failure_reason("Wikipedia", error))
        return ProviderResult(self.name, "complete", documents=[page for page in pages if page])


class _ArticleText(HTMLParser):
    """Keep the paragraph text of a page, and nothing that could run or redirect."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skipping = 0
        self._in_paragraph = 0
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skipping += 1
        elif tag == "p":
            self._in_paragraph += 1
            self.paragraphs.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS and self._skipping:
            self._skipping -= 1
        elif tag == "p" and self._in_paragraph:
            self._in_paragraph -= 1

    def handle_data(self, data: str) -> None:
        if self._in_paragraph and not self._skipping and self.paragraphs:
            self.paragraphs[-1] += data


def page_text(html: str) -> str:
    parser = _ArticleText()
    parser.feed(html)
    parser.close()
    return "\n".join(" ".join(item.split()) for item in parser.paragraphs if item.strip())[:_MAX_DOCUMENT_CHARS]


def _gdelt_date(value: object) -> str | None:
    """GDELT writes 20240305T120000Z. Anything else is dropped rather than guessed."""
    if not isinstance(value, str) or len(value) != 16 or value[8] != "T" or not value.endswith("Z"):
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}T{value[9:11]}:{value[11:13]}:{value[13:15]}Z"


class GdeltProvider:
    """News articles. Only the headline is certain, so each page is also fetched where possible."""

    name = "gdelt"

    def __init__(self, request: Request = safe_request, max_articles: int = 4) -> None:
        self._request = request
        self._max_articles = max_articles

    def _article_text(self, url: str, deadline: float) -> str:
        try:
            response = self._request(
                url, headers={"User-Agent": _HEADERS["User-Agent"], "Accept": "text/html"}, deadline=deadline,
                max_bytes=_MAX_PAGE_BYTES, timeout_s=5.0,
            )
        except (HttpFailed, HttpBlocked):
            return ""
        if response.status != 200 or "html" not in str(response.headers.get("content-type", "")).casefold():
            return ""
        return page_text(response.body.decode("utf-8", errors="replace"))

    def search(self, query: str, deadline: float) -> ProviderResult:
        params = {
            "query": f"{query} sourcelang:english", "mode": "ArtList", "format": "json",
            "maxrecords": str(self._max_articles), "sort": "HybridRel",
        }
        try:
            articles = _get_json(self._request, f"{_GDELT_API}?{urlencode(params)}", deadline).get("articles") or []
            documents: list[Document] = []
            for article in articles[: self._max_articles]:
                url = _public_https(article.get("url"))
                title = str(article.get("title") or "").strip()
                if not url or not title:
                    continue
                body = self._article_text(url, deadline) if time.monotonic() < deadline else ""
                documents.append(
                    Document(
                        self.name, title, url, _domain(url), f"{title}.\n{body}".strip(),
                        date=_gdelt_date(article.get("seendate")), date_kind="first_seen",
                    )
                )
        except _FAILURES as error:
            return ProviderResult(self.name, "unavailable", _failure_reason("GDELT", error))
        return ProviderResult(self.name, "complete", documents=documents)


class FactCheckProvider:
    """Google Fact Check Tools. The key is optional, and without it this says unavailable."""

    name = "google_fact_check"

    def __init__(self, request: Request = safe_request, api_key: str | None = None, max_claims: int = 5) -> None:
        self._request = request
        self._key = api_key if api_key is not None else os.getenv("GOOGLE_FACT_CHECK_API_KEY", "")
        self._max_claims = max_claims

    def search(self, query: str, deadline: float) -> ProviderResult:
        if not self._key:
            return ProviderResult(self.name, "unavailable", "No Google Fact Check API key is set.")
        params = {"query": query, "languageCode": "en", "pageSize": str(self._max_claims), "key": self._key}
        try:
            reply = _get_json(self._request, f"{_FACT_CHECK_API}?{urlencode(params)}", deadline)
            documents: list[Document] = []
            for claim in reply.get("claims") or []:
                reviewed = str(claim.get("text") or "").strip()
                for review in claim.get("claimReview") or []:
                    url = _public_https(review.get("url"))
                    rating = str(review.get("textualRating") or "").strip()
                    if not url or not rating or not reviewed:
                        continue
                    title = str(review.get("title") or reviewed)
                    documents.append(
                        Document(
                            self.name, title, url, _domain(url), title,
                            date=review.get("reviewDate"), date_kind="reviewed", rating=rating, reviewed_claim=reviewed,
                        )
                    )
        except _FAILURES as error:
            return ProviderResult(self.name, "unavailable", _failure_reason("Google Fact Check", error))
        return ProviderResult(self.name, "complete", documents=documents)


def default_providers() -> list[Provider]:
    return [WikipediaProvider(), GdeltProvider(), FactCheckProvider()]
