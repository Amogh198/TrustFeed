"""Mastodon: public hashtag timelines, trending links and account posts, with no login.

Checked 2026-11-05 on four servers: without a login, status search returns nothing. The
link timeline answered for all 3 links trending on mastodon.social, and returned 404 for
a link that wasn't trending. So a link can be traced only while it trends on this server,
and a 404 says nothing about whether anyone posted it.
"""

from typing import Any
from urllib.parse import quote

from backend.network.sources.base import (
    Fetch,
    FetchError,
    PublicPost,
    SearchOutcome,
    SearchQuery,
    text_links,
    count_or_none,
    read_html,
    utc_timestamp,
)

_PAGE_SIZE = 40


class MastodonSource:
    def __init__(self, instance: str = "mastodon.social", platform: str = "mastodon", label: str | None = None) -> None:
        self.instance = instance
        self.platform = platform
        self.label = label or f"Mastodon ({instance})"

    def _qualified(self, acct: str) -> str:
        return acct if "@" in acct else f"{acct}@{self.instance}"

    def _parse(self, status: dict[str, Any]) -> PublicPost | None:
        """Return the post, or None if it isn't a public original post."""
        if status["visibility"] != "public" or status.get("reblog"):
            return None
        account = status["account"]
        acct = self._qualified(account["acct"])
        text, links = read_html(status["content"])
        card = status.get("card") or {}
        return PublicPost(
            platform=self.platform,
            id=f"{self.platform}:{status['uri']}",
            author_id=f"{self.platform}:{acct}",
            author_handle=acct,
            author_ref=str(account["id"]),
            created_at=utc_timestamp(status["created_at"]),
            permalink=status.get("url"),
            text=text,
            url=card.get("url") or next(iter(links), None),
            other_links=tuple(links),
            hashtags=tuple(tag["name"].casefold() for tag in status.get("tags") or ()),
            mentions=tuple(
                (f"{self.platform}:{self._qualified(item['acct'])}", self._qualified(item["acct"]))
                for item in status.get("mentions") or ()
            ),
            followers=int(account.get("followers_count") or 0),
            repost_count=count_or_none(status.get("reblogs_count")),
            image_urls=text_links(
                *(item.get("preview_url") for item in status.get("media_attachments") or () if isinstance(item, dict))
            ),
        )

    def _read(self, statuses: Any, outcome: SearchOutcome) -> None:
        for status in statuses if isinstance(statuses, list) else ():
            try:
                post = self._parse(status)
            except (KeyError, TypeError, ValueError, AttributeError):
                outcome.malformed += 1
                continue
            if post is not None:
                outcome.posts.append(post)

    def search(self, query: SearchQuery, fetch: Fetch) -> SearchOutcome:
        outcome = SearchOutcome()
        if query.phrases:
            outcome.unsupported.append("Text can't be searched here without a login.")
        if query.all_urls:
            outcome.unsupported.append(
                "Without a login, a link can be found here only while it is trending on this server, "
                "so finding nothing doesn't show it wasn't posted."
            )
        for link in query.all_urls:
            address = f"https://{self.instance}/api/v1/timelines/link?url={quote(link, safe='')}&limit={_PAGE_SIZE}"
            try:
                statuses = fetch(address)
            except FetchError as error:
                if error.status != 404:  # A 404 only means the link isn't trending here.
                    outcome.searches_run += 1
                    outcome.failures.append(str(error))
                continue
            outcome.searches_run += 1
            self._read(statuses, outcome)
        for tag in query.hashtags:
            address = f"https://{self.instance}/api/v1/timelines/tag/{quote(tag, safe='')}?limit={_PAGE_SIZE}"
            outcome.searches_run += 1
            try:
                self._read(fetch(address), outcome)
            except FetchError as error:
                outcome.failures.append(str(error))
        return outcome

    def author_posts(self, post: PublicPost, fetch: Fetch) -> list[PublicPost]:
        address = (
            f"https://{self.instance}/api/v1/accounts/{quote(post.author_ref, safe='')}/statuses"
            f"?limit={_PAGE_SIZE}&exclude_reblogs=true"
        )
        outcome = SearchOutcome()
        self._read(fetch(address), outcome)
        return outcome.posts
