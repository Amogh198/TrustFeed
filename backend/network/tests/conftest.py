import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# Lets a bare `pytest` find the backend package from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def stamp(seconds: float) -> str:
    return (START + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def make_dataset():
    """Build a raw dataset from (account, seconds, url, media, text, mentions) tuples."""

    def build(rows, extra_accounts=(), synthetic=True):
        accounts = sorted({row[0] for row in rows} | {m for row in rows for m in (row[5] if len(row) > 5 else ())} | set(extra_accounts))
        return {
            "metadata": {"case_id": "test-case", "synthetic": synthetic},
            "accounts": [{"id": account, "handle": f"handle_{account}"} for account in accounts],
            "posts": [
                {
                    "id": f"p{index:04d}",
                    "account_id": row[0],
                    "created_at": stamp(row[1]),
                    "url": row[2] if len(row) > 2 else None,
                    "media_hash": row[3] if len(row) > 3 else None,
                    "text": row[4] if len(row) > 4 else "",
                    "mentions": list(row[5]) if len(row) > 5 else [],
                }
                for index, row in enumerate(rows)
            ],
        }

    return build


@pytest.fixture
def ring_rows():
    """Build posts for a ring where every member shares every item within seconds."""

    def build(members, items=3, prefix="item", start=0, mentions=()):
        rows = []
        for item in range(items):
            base = start + item * 3600
            for offset, member in enumerate(members):
                rows.append(
                    (
                        member,
                        base + offset * 2,
                        f"https://site.example/{prefix}/{item}",
                        f"{prefix}hash{item}",
                        f"Identical copied message about {prefix} number {item}",
                        mentions,
                    )
                )
        return rows

    return build
