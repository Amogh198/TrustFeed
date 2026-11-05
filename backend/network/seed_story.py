"""Build the demo story's recording by running a real trace against an invented world.

Every response is produced in the platform's real format and captured from the requests
the adapters actually make, so the fixture can't drift from the code that reads it. All
data is invented, deterministic and written to ``data/demo/network_demo_story.json``.

Run ``python -m backend.network.seed_story``, or add ``--check`` to compare with the file.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from backend.network.dataset import DEMO_STORY_PATH
from backend.network.seed_network import render
from backend.network.sources import FetchError, RecordingFetch
from backend.network.story import story_sources
from backend.network.trace import trace_public_spread

NOTICE = (
    "SYNTHETIC DEMO DATA: an invented rumour about a fictional town, posted by invented accounts "
    "on invented platforms. It is not evidence of real-world activity by any person or group."
)
RECORDED_AT = "2026-02-10T18:00:00Z"
_START = datetime(2026, 2, 10, 6, 0, tzinfo=UTC)
_SOCIAL = "story-social.example"
_FORUM = "story-lemmy.example"
_HASHTAG = "ElmbrookDam"
_TARGET = f"synthetic_story_mayor@{_SOCIAL}"

SUBMISSION = {
    "text": (
        "BREAKING: the Elmbrook dam has failed and officials are hiding it, "
        f"share before this is deleted #{_HASHTAG}"
    ),
    "url": "https://elmbrook-alerts.example/dam-failure",
}
_ITEMS = (
    (SUBMISSION["url"], SUBMISSION["text"]),
    (
        "https://elmbrook-alerts.example/evacuation-order",
        "Elmbrook evacuation order leaked, the council is telling only its own families to leave tonight",
    ),
    (
        "https://elmbrook-alerts.example/water-warning",
        "Elmbrook tap water is now unsafe after the dam failure and the hospital was told to stay silent",
    ),
)
_WAVE_OFFSETS_MINUTES = (0, 47, 133)
_RING_DELAY_SECONDS = 9
# How the invented accounts are spread across the three invented platforms.
_RING = (("social", 5), ("forum", 4), ("news", 3))
_RESIDENT_TEXT = "Has anyone else seen this photo of the Elmbrook dam? I can't tell whether it is real."
_LATE_REPLIES = (
    ("news", "Is this Elmbrook story confirmed by anyone? Looks odd to me."),
    ("social", f"Please check this before sharing, nobody official has said it #{_HASHTAG}"),
    ("forum", "Local here. I just walked past the dam and it looks fine to me."),
)


def _at(minutes: float, seconds: float = 0) -> str:
    return (_START + timedelta(minutes=minutes, seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _world() -> dict[str, list[dict[str, Any]]]:
    """Return every invented post, as neutral records grouped by platform."""
    posts: dict[str, list[dict[str, Any]]] = {"social": [], "forum": [], "news": []}
    index = 0
    for platform, count in _RING:
        for _ in range(count):
            account = f"synthetic_story_ring{index:02d}"
            for wave, (url, text) in enumerate(_ITEMS):
                posts[platform].append(
                    {
                        "id": f"ring{index:02d}-{wave}",
                        "account": account,
                        "at": _at(_WAVE_OFFSETS_MINUTES[wave], index * _RING_DELAY_SECONDS),
                        "text": text,
                        "url": url,
                        "mention_target": True,
                    }
                )
            index += 1

    # A resident asks about the photo hours before the campaign, so the earliest post
    # found isn't part of it. A trace must not mistake this person for the source.
    posts["forum"].append(
        {"id": "resident", "account": "synthetic_story_resident", "at": _at(-185), "text": _RESIDENT_TEXT, "url": SUBMISSION["url"]}
    )
    for position, (platform, text) in enumerate(_LATE_REPLIES):
        posts[platform].append(
            {
                "id": f"late-{position}",
                "account": f"synthetic_story_late{position}",
                "at": _at(240 + position * 70),
                "text": text,
                "url": SUBMISSION["url"],
            }
        )
    # Search results that look relevant but carry a different link, which must be dropped.
    for platform in ("forum", "news"):
        posts[platform].append(
            {
                "id": f"decoy-{platform}",
                "account": f"synthetic_story_decoy_{platform}",
                "at": _at(30),
                "text": "Elmbrook dam maintenance schedule published for next spring by the water board",
                "url": "https://elmbrook-council.example/maintenance",
            }
        )
    return posts


def _account_number(account: str) -> int:
    return sum(ord(character) * (position + 1) for position, character in enumerate(account))


def _as_mastodon(post: dict[str, Any]) -> dict[str, Any]:
    account = post["account"]
    tags = [_HASHTAG] if post["url"] == SUBMISSION["url"] else []
    mention = (
        f'<a class="u-url mention" href="https://{_SOCIAL}/@synthetic_story_mayor">@synthetic_story_mayor</a> '
        if post.get("mention_target")
        else ""
    )
    return {
        "uri": f"https://{_SOCIAL}/users/{account}/statuses/{post['id']}",
        "url": f"https://{_SOCIAL}/@{account}/{post['id']}",
        "created_at": post["at"],
        "visibility": "public",
        "reblog": None,
        "content": f'<p>{mention}{post["text"]} <a href="{post["url"]}">{post["url"]}</a></p>',
        "card": None,
        "tags": [{"name": tag} for tag in tags],
        "mentions": [{"acct": _TARGET}] if post.get("mention_target") else [],
        "account": {"id": str(_account_number(account)), "acct": f"{account}@{_SOCIAL}", "followers_count": 40},
    }


def _as_lemmy(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "post": {
            "ap_id": f"https://{_FORUM}/post/{post['id']}",
            "name": post["text"],
            "url": post["url"],
            "published": post["at"],
        },
        "creator": {"name": post["account"], "actor_id": f"https://{_FORUM}/u/{post['account']}"},
    }


def _as_algolia(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "objectID": post["id"],
        "author": post["account"],
        "created_at": post["at"],
        "title": post["text"],
        "url": post["url"],
    }


class _InventedWorld:
    """Answer each platform's API from the invented posts, as the real services would."""

    def __init__(self) -> None:
        self.posts = _world()

    def _search_results(self, platform: str) -> list[dict[str, Any]]:
        # Loose, like real search: decoys come back too, so the trace must filter them out.
        return [
            post for post in self.posts[platform]
            if post["url"] == SUBMISSION["url"] or post["id"].startswith("decoy")
        ]

    def __call__(self, address: str) -> Any:
        parts = urlsplit(address)
        query = parse_qs(parts.query)
        if parts.netloc == _SOCIAL and "/timelines/tag/" in parts.path:
            tag = unquote(parts.path.rsplit("/", 1)[1]).casefold()
            wanted = [post for post in self.posts["social"] if _HASHTAG.casefold() == tag and post["url"] == SUBMISSION["url"]]
            return [_as_mastodon(post) for post in wanted]
        if parts.netloc == _SOCIAL and parts.path.endswith("/statuses"):
            number = parts.path.split("/")[-2]
            return [_as_mastodon(post) for post in self.posts["social"] if str(_account_number(post["account"])) == number]
        if parts.netloc == _FORUM and parts.path.endswith("/search"):
            return {"posts": [_as_lemmy(post) for post in self._search_results("forum")]}
        if parts.netloc == _FORUM and parts.path.endswith("/user"):
            name = query["username"][0].split("@")[0]
            return {"posts": [_as_lemmy(post) for post in self.posts["forum"] if post["account"] == name]}
        if parts.netloc == "hn.algolia.com" and "query" in query:
            return {"hits": [_as_algolia(post) for post in self._search_results("news")]}
        if parts.netloc == "hn.algolia.com":
            author = query["tags"][0].split("author_")[1]
            return {"hits": [_as_algolia(post) for post in self.posts["news"] if post["account"] == author]}
        raise FetchError("The invented world has no such endpoint")


def build_story() -> dict[str, Any]:
    recorder = RecordingFetch(_InventedWorld())
    trace_public_spread(
        "demo-story-build", text=SUBMISSION["text"], url=SUBMISSION["url"], sources=story_sources(), fetch=recorder
    )
    return {
        "synthetic": True,
        "notice": NOTICE,
        "recorded_at": RECORDED_AT,
        "submission": SUBMISSION,
        "responses": dict(sorted(recorder.responses.items())),
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    story = build_story()
    if "--check" in args:
        current = json.loads(DEMO_STORY_PATH.read_text(encoding="utf-8")) if DEMO_STORY_PATH.exists() else None
        if current != story:
            print("The story recording is out of date. Run: python -m backend.network.seed_story")
            return 1
        print("The story recording matches the generator.")
        return 0
    DEMO_STORY_PATH.write_text(render(story), encoding="utf-8", newline="\n")
    print(f"Wrote {DEMO_STORY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
