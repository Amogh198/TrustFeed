"""Lemmy: public search across the instances one server federates with, with no login."""

from typing import Any
from urllib.parse import quote, urlsplit

from backend.network.sources.base import (
    Fetch,
    FetchError,
    PublicPost,
    SearchOutcome,
    SearchQuery,
    utc_timestamp,
)

_PAGE_SIZE = 50


class LemmySource:
    def __init__(self, instance: str = "lemmy.world", platform: str = "lemmy", label: str | None = None) -> None:
        self.instance = instance
        self.platform = platform
        self.label = label or f"Lemmy (as seen from {instance})"

    def _parse(self, view: dict[str, Any]) -> PublicPost | None:
        post = view["post"]
        creator = view["creator"]
        if post.get("deleted") or post.get("removed"):
            return None
        handle = f"{creator['name']}@{urlsplit(creator['actor_id']).netloc}"
        return PublicPost(
            platform=self.platform,
            id=f"{self.platform}:{post['ap_id']}",
            author_id=f"{self.platform}:{creator['actor_id']}",
            author_handle=handle,
            author_ref=handle,
            created_at=utc_timestamp(post["published"]),
            permalink=post["ap_id"],
            text=" ".join(part for part in (post.get("name"), post.get("body")) if part),
            url=post.get("url"),
        )

    def _read(self, views: Any, outcome: SearchOutcome) -> None:
        for view in views if isinstance(views, list) else ():
            try:
                post = self._parse(view)
            except (KeyError, TypeError, ValueError, AttributeError):
                outcome.malformed += 1
                continue
            if post is not None:
                outcome.posts.append(post)

    def search(self, query: SearchQuery, fetch: Fetch) -> SearchOutcome:
        outcome = SearchOutcome()
        if query.hashtags:
            outcome.unsupported.append("Lemmy has no hashtags, so hashtags weren't searched here.")
        searches = [("Url", url) for url in query.urls] + [("Posts", phrase) for phrase in query.phrases]
        for kind, term in searches:
            address = (
                f"https://{self.instance}/api/v3/search?q={quote(term, safe='')}"
                f"&type_={kind}&listing_type=All&sort=New&limit={_PAGE_SIZE}"
            )
            outcome.searches_run += 1
            try:
                response = fetch(address)
            except FetchError as error:
                outcome.failures.append(str(error))
                continue
            self._read(response.get("posts") if isinstance(response, dict) else None, outcome)
        return outcome

    def author_posts(self, post: PublicPost, fetch: Fetch) -> list[PublicPost]:
        address = (
            f"https://{self.instance}/api/v3/user?username={quote(post.author_ref, safe='')}"
            f"&sort=New&limit={_PAGE_SIZE}"
        )
        outcome = SearchOutcome()
        response = fetch(address)
        self._read(response.get("posts") if isinstance(response, dict) else None, outcome)
        return outcome.posts
