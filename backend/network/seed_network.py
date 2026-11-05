"""Deterministic generator for the synthetic dissemination demo dataset.

Run from the repository root:

    python -m backend.network.seed_network          # write the fixtures
    python -m backend.network.seed_network --check  # fail if they are out of date

All accounts, posts, links and media hashes are invented. Links use the reserved
``.example`` domain, and the campaign is about a fictional town.
"""

import argparse
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.network.dataset import DEMO_DATASET_PATH, format_timestamp

GROUND_TRUTH_PATH = DEMO_DATASET_PATH.with_name("network_demo_ground_truth.json")
SEED = 20261105
CASE_ID = "demo-001"
NOTICE = (
    "SYNTHETIC DEMO DATA. Every account, post, link and media hash is invented by "
    "backend/network/seed_network.py. Results from this file are not evidence of "
    "real-world activity by any person or group."
)

_START = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
_TOTAL_ACCOUNTS = 320
_CORE_MEMBERS = 30  # Including the seed account.
_PERIPHERAL_MEMBERS = 6
_TARGETS = 3
_SYNDICATION_GROUP = 3
_ORGANIC_BURST = 24
_LATE_RESHARERS = 15

# Each campaign wave stays inside the 120-second co-share window.
_WAVE_OFFSETS_MINUTES = (0, 47, 133, 220)
_WAVE_MIN_DELAY_SECONDS = 8
_WAVE_MAX_DELAY_SECONDS = 110

# Invented names, so that no real platform is implied to host this activity.
_PLATFORMS = ("demo_forum", "demo_microblog", "demo_video")

_CAMPAIGN_TEXTS = (
    "Northbridge reservoir declared unsafe, officials are hiding the test results",
    "Leaked memo says Northbridge water rationing starts this weekend",
    "Northbridge hospital staff told not to talk about the water contamination",
    "Share before this is deleted: Northbridge council knew about the water for months",
)
_SYNDICATED_TEXTS = (
    "Northbridge Daily headline: road repairs begin on Mill Street next week",
    "Northbridge Daily headline: community library extends its weekend hours",
    "Northbridge Daily headline: annual harvest fair announces this year's dates",
)
_CHATTER_TOPICS = (
    "the morning commute",
    "the school science fair",
    "weekend football results",
    "the new bakery on Station Road",
    "this week's weather",
    "the farmers market",
    "a good book recommendation",
    "the community garden",
)


@dataclass
class _Builder:
    rng: random.Random
    posts: list[dict[str, Any]] = field(default_factory=list)

    def media_hash(self) -> str:
        return f"{self.rng.getrandbits(64):016x}"

    def post(
        self,
        account_id: str,
        created_at: datetime,
        text: str,
        url: str | None = None,
        media_hash: str | None = None,
        mentions: list[str] | None = None,
        hashtags: list[str] | None = None,
    ) -> None:
        self.posts.append(
            {
                "account_id": account_id,
                "created_at": format_timestamp(created_at),
                "text": text,
                "url": url,
                "media_hash": media_hash,
                "mentions": mentions or [],
                "hashtags": hashtags or [],
                "synthetic": True,
            }
        )


def _disguise(rng: random.Random, text: str) -> str:
    """Vary case and punctuation, as copied posts do to avoid an exact match."""
    style = rng.randrange(4)
    if style == 0:
        return text.upper()
    if style == 1:
        return f"{text}!!"
    if style == 2:
        return f"...{text.lower()}..."
    return text


def _add_campaign(
    builder: _Builder, seed_account: str, core: list[str], peripheral: list[str], targets: list[str]
) -> None:
    rng = builder.rng
    items = [
        (text, f"https://northbridge-alerts.example/story/{index}", builder.media_hash())
        for index, text in enumerate(_CAMPAIGN_TEXTS, start=1)
    ]
    # Peripheral accounts join two waves only, so they stay less connected than the core.
    second_wave_by_peripheral = {account: rng.randrange(1, len(items)) for account in peripheral}

    for wave, (text, url, media) in enumerate(items):
        wave_start = _START + timedelta(minutes=_WAVE_OFFSETS_MINUTES[wave])
        builder.post(seed_account, wave_start, text, url, media, [targets[wave % len(targets)]], ["#NorthbridgeWater"])

        participants = [account for account in core if wave == 0 or rng.random() > 0.1]
        participants += [
            account
            for account in peripheral
            if wave == 0 or second_wave_by_peripheral[account] == wave
        ]
        for account in participants:
            delay = rng.randint(_WAVE_MIN_DELAY_SECONDS, _WAVE_MAX_DELAY_SECONDS)
            # Tracking parameters make the links differ until they are normalized.
            builder.post(
                account,
                wave_start + timedelta(seconds=delay),
                _disguise(rng, text),
                f"{url}?utm_source={account}",
                media,
                [rng.choice(targets)],
                ["#NorthbridgeWater"],
            )


def _add_late_reshares(builder: _Builder, accounts: list[str]) -> None:
    """Hard negative: genuine-looking reshares of a campaign item, hours later and spread out."""
    url = "https://northbridge-alerts.example/story/1"
    for index, account in enumerate(accounts):
        created_at = _START + timedelta(hours=5, minutes=25 * index)
        builder.post(account, created_at, f"Has anyone checked this? Reader question number {index + 1} about the reservoir story", url)


def _add_organic_burst(builder: _Builder, accounts: list[str]) -> None:
    """Hard negative: many accounts react at once to one event, each in their own words."""
    rng = builder.rng
    url = "https://regional-news.example/northbridge-bridge-reopens"
    start = _START + timedelta(hours=14)
    for index, account in enumerate(accounts):
        builder.post(
            account,
            start + timedelta(seconds=rng.randint(0, 110)),
            f"Personal reaction {index + 1}: glad the bridge is finally open, my route is {rng.randint(5, 40)} minutes shorter",
            url,
        )


def _add_syndication(builder: _Builder, accounts: list[str]) -> None:
    """Hard negative: a small group that really is automated, but openly and too small to flag."""
    rng = builder.rng
    for index, text in enumerate(_SYNDICATED_TEXTS):
        start = _START + timedelta(hours=18 + 2 * index)
        url = f"https://northbridge-daily.example/article/{index + 1}"
        for account in accounts:
            builder.post(account, start + timedelta(seconds=rng.randint(0, 30)), text, url)


def _add_background(builder: _Builder, organic: list[str]) -> None:
    rng = builder.rng
    popular_urls = [f"https://regional-news.example/story/{index}" for index in range(1, 41)]
    counter = 0
    for account in organic:
        for _ in range(rng.randint(1, 4)):
            counter += 1
            created_at = _START + timedelta(seconds=rng.randint(-6 * 3600, 30 * 3600))
            builder.post(
                account,
                created_at,
                f"Synthetic chatter {counter}: thoughts on {rng.choice(_CHATTER_TOPICS)}",
                rng.choice(popular_urls) if rng.random() < 0.25 else None,
                builder.media_hash() if rng.random() < 0.1 else None,
                [rng.choice(organic)] if rng.random() < 0.15 else None,
            )


def build_demo_dataset(seed: int = SEED) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(dataset, ground_truth)``. The engine never reads the ground truth."""
    rng = random.Random(seed)
    account_ids = [f"acct_{index:04d}" for index in range(1, _TOTAL_ACCOUNTS + 1)]
    accounts = [
        {
            "id": account_id,
            "handle": f"synthetic_user_{account_id[5:]}",
            "created_at": format_timestamp(_START - timedelta(days=rng.randint(30, 1500))),
            "followers": rng.randint(5, 5000),
            "platform": rng.choice(_PLATFORMS),
            "synthetic": True,
        }
        for account_id in account_ids
    ]

    # Shuffled so that an account's id reveals nothing about its group.
    shuffled = rng.sample(account_ids, len(account_ids))

    def take(count: int) -> list[str]:
        taken = shuffled[:count]
        del shuffled[:count]
        return sorted(taken)

    seed_account = take(1)[0]
    core = take(_CORE_MEMBERS - 1)
    peripheral = take(_PERIPHERAL_MEMBERS)
    targets = take(_TARGETS)
    syndication = take(_SYNDICATION_GROUP)
    organic_burst = take(_ORGANIC_BURST)
    late_resharers = take(_LATE_RESHARERS)
    organic = sorted([*shuffled, *organic_burst, *late_resharers, *targets])

    builder = _Builder(rng)
    _add_campaign(builder, seed_account, core, peripheral, targets)
    _add_late_reshares(builder, late_resharers)
    _add_organic_burst(builder, organic_burst)
    _add_syndication(builder, syndication)
    _add_background(builder, organic)

    posts = sorted(builder.posts, key=lambda post: (post["created_at"], post["account_id"], post["text"]))
    platform_of = {account["id"]: account["platform"] for account in accounts}
    for index, post in enumerate(posts, start=1):
        post["platform"] = platform_of[post["account_id"]]
        post["id"] = f"post_{index:05d}"

    dataset = {
        "metadata": {
            "case_id": CASE_ID,
            "synthetic": True,
            "notice": NOTICE,
            "generator": "backend/network/seed_network.py",
            "seed": seed,
            "schema_version": 1,
        },
        "accounts": accounts,
        "posts": posts,
    }
    ground_truth = {
        "synthetic": True,
        "notice": f"{NOTICE} Test labels only: the analysis engine must never read this file.",
        "seed": seed,
        "seed_account": seed_account,
        "coordinated_accounts": sorted([seed_account, *core, *peripheral]),
        "peripheral_accounts": peripheral,
        "target_accounts": targets,
        "hard_negatives": {
            "organic_burst": organic_burst,
            "late_resharers": late_resharers,
            "syndication_group": syndication,
        },
    }
    return dataset, ground_truth


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=1, sort_keys=True, ensure_ascii=True) + "\n"


def _matches_on_disk(path: Path, document: dict[str, Any]) -> bool:
    # Compares parsed JSON so that Windows line endings from git do not count as a change.
    return path.exists() and json.loads(path.read_text(encoding="utf-8")) == document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the fixtures are out of date")
    args = parser.parse_args(argv)

    dataset, ground_truth = build_demo_dataset()
    files = ((DEMO_DATASET_PATH, dataset), (GROUND_TRUTH_PATH, ground_truth))

    if args.check:
        stale = [path.name for path, document in files if not _matches_on_disk(path, document)]
        if stale:
            print(f"Out of date: {', '.join(stale)}. Run python -m backend.network.seed_network")
            return 1
        print("Fixtures match the generator.")
        return 0

    for path, document in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(render(document))
        print(f"Wrote {path.name}")
    print(f"{len(dataset['accounts'])} accounts, {len(dataset['posts'])} posts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
