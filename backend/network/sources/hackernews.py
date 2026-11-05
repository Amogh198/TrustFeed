"""Hacker News: public stories and comments through the Algolia search API, with no login."""

from typing import Any
from urllib.parse import quote

from backend.network.sources.base import (
    Fetch,
    FetchError,
    PublicPost,
    SearchOutcome,
    SearchQuery,
    read_html,
    utc_timestamp,
)

_BASE = "https://hn.algolia.com/api/v1/search_by_date"
_PAGE_SIZE = 50


class HackerNewsSource:
    def __init__(self, platform: str = "hackernews", label: str = "Hacker News") -> None:
        self.platform = platform
        self.label = label

    def _parse(self, hit: dict[str, Any]) -> PublicPost:
        author = hit["author"]
        body, links = read_html(hit.get("story_text") or hit.get("comment_text") or "")
        return PublicPost(
            platform=self.platform,
            id=f"{self.platform}:{hit['objectID']}",
            author_id=f"{self.platform}:{author}",
            author_handle=author,
            author_ref=author,
            created_at=utc_timestamp(hit["created_at"]),
            permalink=f"https://news.ycombinator.com/item?id={hit['objectID']}",
            text=" ".join(part for part in (hit.get("title"), body) if part),
            url=hit.get("url") or next(iter(links), None),
        )

    def _read(self, response: Any, outcome: SearchOutcome) -> None:
        hits = response.get("hits") if isinstance(response, dict) else None
        for hit in hits if isinstance(hits, list) else ():
            try:
                outcome.posts.append(self._parse(hit))
            except (KeyError, TypeError, ValueError, AttributeError):
                outcome.malformed += 1

    def search(self, query: SearchQuery, fetch: Fetch) -> SearchOutcome:
        outcome = SearchOutcome()
        if query.hashtags:
            outcome.unsupported.append("Hacker News has no hashtags, so hashtags weren't searched here.")
        addresses = [
            f"{_BASE}?query={quote(url, safe='')}&restrictSearchableAttributes=url&tags=story&hitsPerPage={_PAGE_SIZE}"
            for url in query.urls
        ] + [
            f"{_BASE}?query={quote(chr(34) + phrase + chr(34), safe='')}&tags=(story,comment)&hitsPerPage={_PAGE_SIZE}"
            for phrase in query.phrases
        ]
        for address in addresses:
            outcome.searches_run += 1
            try:
                self._read(fetch(address), outcome)
            except FetchError as error:
                outcome.failures.append(str(error))
        return outcome

    def author_posts(self, post: PublicPost, fetch: Fetch) -> list[PublicPost]:
        address = f"{_BASE}?tags=story,author_{quote(post.author_ref, safe='')}&hitsPerPage={_PAGE_SIZE}"
        outcome = SearchOutcome()
        self._read(fetch(address), outcome)
        return outcome.posts
