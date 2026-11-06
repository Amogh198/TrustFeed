"""Bluesky: public post search by link, hashtag or phrase, with no login.

Checked 2026-11-05: search answers on ``api.bsky.app`` without a login, while
``public.api.bsky.app`` returned 403 and ``bsky.social`` returned 401. This is tested
behaviour, not a promise, so a refusal is reported as a failed search.
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
    utc_timestamp,
)

_SEARCH = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
_AUTHOR_FEED = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
_PAGE_SIZE = 100
# Set by people who asked that logged-out viewers not see their posts. Respect it.
_NO_LOGGED_OUT_VIEWERS = "!no-unauthenticated"


def _features(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [feature for facet in record.get("facets") or () for feature in facet.get("features") or ()]


def _feature_values(record: dict[str, Any], kind: str, field: str) -> list[str]:
    return [item[field] for item in _features(record) if item.get("$type") == f"app.bsky.richtext.facet#{kind}"]


def _picture_links(view: dict[str, Any]) -> tuple[str, ...]:
    """Find thumbnails in a post's embed, including a video's and a quote post's own media."""
    embed = view.get("embed")
    embed = embed if isinstance(embed, dict) else {}
    media = embed.get("media") if isinstance(embed.get("media"), dict) else embed
    images = media.get("images") if isinstance(media.get("images"), list) else []
    external = media.get("external") if isinstance(media.get("external"), dict) else {}
    return text_links(
        *(image.get("thumb") for image in images if isinstance(image, dict)), media.get("thumbnail"), external.get("thumb")
    )


def _has_label(view: dict[str, Any], value: str) -> bool:
    labels = [*(view.get("labels") or ()), *(view["author"].get("labels") or ())]
    return any(label.get("val") == value for label in labels)


class BlueskySource:
    platform = "bluesky"
    label = "Bluesky"

    def _parse(self, view: dict[str, Any]) -> PublicPost | None:
        if _has_label(view, _NO_LOGGED_OUT_VIEWERS):
            return None
        author = view["author"]
        record = view["record"]
        did, handle = author["did"], author["handle"]
        embed = record.get("embed") or {}
        embedded = (embed.get("external") or {}).get("uri")
        links = [*([embedded] if embedded else []), *_feature_values(record, "link", "uri")]
        return PublicPost(
            platform=self.platform,
            id=f"bluesky:{view['uri']}",
            author_id=f"bluesky:{did}",
            author_handle=handle,
            author_ref=did,
            # The time Bluesky saw the post. Its createdAt is set by the poster's app.
            created_at=utc_timestamp(view["indexedAt"]),
            permalink=f"https://bsky.app/profile/{handle}/post/{view['uri'].rsplit('/', 1)[-1]}",
            text=record["text"],
            url=links[0] if links else None,
            other_links=tuple(links[1:]),
            hashtags=tuple(
                tag.casefold() for tag in [*_feature_values(record, "tag", "tag"), *(record.get("tags") or ())]
            ),
            # Search results give only an account's id for a mention, not its handle.
            mentions=tuple((f"bluesky:{item}", item) for item in _feature_values(record, "mention", "did")),
            repost_count=count_or_none(view.get("repostCount")),
            image_urls=_picture_links(view),
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
        addresses = [
            *(f"{_SEARCH}?q=*&url={quote(url, safe='')}&sort=latest&limit={_PAGE_SIZE}" for url in query.all_urls),
            *(f"{_SEARCH}?q=*&tag={quote(tag, safe='')}&sort=latest&limit={_PAGE_SIZE}" for tag in query.hashtags),
            *(
                f"{_SEARCH}?q={quote(chr(34) + phrase + chr(34), safe='')}&sort=latest&limit={_PAGE_SIZE}"
                for phrase in query.phrases
            ),
        ]
        for address in addresses:
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
            f"{_AUTHOR_FEED}?actor={quote(post.author_ref, safe='')}"
            f"&filter=posts_no_replies&limit={_PAGE_SIZE}"
        )
        response = fetch(address)
        items = response.get("feed") if isinstance(response, dict) else None
        # An item with a reason is a repost by this author, not their own post.
        views = [item.get("post") for item in items or () if isinstance(item, dict) and not item.get("reason")]
        outcome = SearchOutcome()
        self._read(views, outcome)
        return outcome.posts
