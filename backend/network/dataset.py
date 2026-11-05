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
    platform: str | None = None
    # True when this post was collected because it carries the content being traced.
    on_topic: bool = False


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


def _records(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    records = raw.get(key, [])
    if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
        raise ValueError(f"Dataset {key} must be a list of records")
    return records


def _required_text(record: dict[str, Any], field: str, kind: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{kind} record needs a non-empty text {field}: {record.get('id')!r}")
    return value


def _optional_text(record: dict[str, Any], field: str, kind: str) -> str | None:
    value = record.get(field)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{kind} {record.get('id')!r} has a non-text {field}")
    return value


def _parse_account(record: dict[str, Any]) -> Account:
    followers = record.get("followers", 0)
    if not isinstance(followers, int) or isinstance(followers, bool):
        raise ValueError(f"Account {record.get('id')!r} has non-integer followers")  # noqa: TRY004
    return Account(
        id=_required_text(record, "id", "Account"),
        handle=_required_text(record, "handle", "Account"),
        followers=followers,
    )


def _parse_post(record: dict[str, Any]) -> Post:
    post_id = _required_text(record, "id", "Post")
    mentions = record.get("mentions") or ()
    if not isinstance(mentions, list | tuple) or not all(isinstance(item, str) for item in mentions):
        raise ValueError(f"Post {post_id!r} mentions must be a list of account ids")
    return Post(
        id=post_id,
        account_id=_required_text(record, "account_id", "Post"),
        created_at=parse_timestamp(_required_text(record, "created_at", "Post")),
        text=_optional_text(record, "text", "Post") or "",
        url=_optional_text(record, "url", "Post"),
        media_hash=_optional_text(record, "media_hash", "Post"),
        mentions=tuple(mentions),
        platform=_optional_text(record, "platform", "Post"),
        on_topic=record.get("on_topic") is True,
    )


def parse_dataset(raw: dict[str, Any]) -> Dataset:
    """Build a validated Dataset. Any record that would corrupt the graph raises ValueError."""
    metadata = raw.get("metadata")
    if not isinstance(metadata, dict) or not metadata.get("case_id") or not isinstance(metadata["case_id"], str):
        raise ValueError("Dataset metadata must include a case_id")

    accounts = tuple(_parse_account(item) for item in _records(raw, "accounts"))
    _require_unique([account.id for account in accounts], "account")
    known_accounts = {account.id for account in accounts}

    posts = []
    for item in _records(raw, "posts"):
        post = _parse_post(item)
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
