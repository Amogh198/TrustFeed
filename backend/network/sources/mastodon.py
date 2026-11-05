"""Mastodon: public hashtag timelines and account posts, with no login.

Checked 2026-11-05 on mastodon.social: without a login, searching post text returns
nothing and the link timeline returns 404, so only hashtags can be searched.
"""

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

_PAGE_SIZE = 40


class MastodonSource:
    platform = "mastodon"

    def __init__(self, instance: str = "mastodon.social") -> None:
        self.instance = instance
        self.label = f"Mastodon ({instance})"

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
            id=f"mastodon:{status['uri']}",
            author_id=f"mastodon:{acct}",
            author_handle=acct,
            author_ref=str(account["id"]),
            created_at=utc_timestamp(status["created_at"]),
            permalink=status.get("url"),
            text=text,
            url=card.get("url") or next(iter(links), None),
            hashtags=tuple(tag["name"].casefold() for tag in status.get("tags") or ()),
            mentions=tuple(
                (f"mastodon:{self._qualified(item['acct'])}", self._qualified(item["acct"]))
                for item in status.get("mentions") or ()
            ),
            followers=int(account.get("followers_count") or 0),
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
        if query.urls or query.phrases:
            outcome.unsupported.append("Links and text can't be searched here without a login; only hashtags can.")
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
