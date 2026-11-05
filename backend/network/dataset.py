"""Parsing and validation of social-post datasets."""

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEMO_DATASET_PATH = Path(__file__).resolve().parents[2] / "data" / "demo" / "network_demo.json"


@dataclass(frozen=True)
class Account:
    id: str
    handle: str
    followers: int = 0


@dataclass(frozen=True)
class Post:
    id: str
    account_id: str
    created_at: datetime
    text: str = ""
    url: str | None = None
    media_hash: str | None = None
    mentions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Dataset:
    case_id: str
    synthetic: bool
    accounts: tuple[Account, ...]
    # Sorted by (created_at, id) so every later step is order-independent.
    posts: tuple[Post, ...]


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include a timezone: {value!r}")
    return parsed.astimezone(UTC)


def format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_unique(ids: list[str], kind: str) -> None:
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate {kind} ids: {duplicates[:5]}")


def parse_dataset(raw: dict[str, Any]) -> Dataset:
    """Build a validated Dataset, rejecting records that would corrupt the graph."""
    metadata = raw.get("metadata")
    if not isinstance(metadata, dict) or not metadata.get("case_id"):
        raise ValueError("Dataset metadata must include a case_id")

    accounts = tuple(
        Account(id=item["id"], handle=item["handle"], followers=item.get("followers", 0))
        for item in raw.get("accounts", [])
    )
    _require_unique([account.id for account in accounts], "account")
    known_accounts = {account.id for account in accounts}

    posts = []
    for item in raw.get("posts", []):
        post = Post(
            id=item["id"],
            account_id=item["account_id"],
            created_at=parse_timestamp(item["created_at"]),
            text=item.get("text") or "",
            url=item.get("url"),
            media_hash=item.get("media_hash"),
            mentions=tuple(item.get("mentions") or ()),
        )
        unknown = {post.account_id, *post.mentions} - known_accounts
        if unknown:
            raise ValueError(f"Post {post.id} references unknown accounts: {sorted(unknown)}")
        posts.append(post)
    _require_unique([post.id for post in posts], "post")

    return Dataset(
        case_id=metadata["case_id"],
        # Only an explicit true counts, so a missing flag never claims "synthetic".
        synthetic=metadata.get("synthetic") is True,
        accounts=accounts,
        posts=tuple(sorted(posts, key=lambda post: (post.created_at, post.id))),
    )


def load_dataset(path: Path = DEMO_DATASET_PATH) -> Dataset:
    with path.open(encoding="utf-8") as handle:
        return parse_dataset(json.load(handle))
