"""Tests that let a coordination search come back with nothing.

Reimplements a common idea from coordination research, including OSoMe's published work:
compare what was observed with what the same posts give when their timing is scrambled. No
code was copied. None of these shows that accounts are coordinating. They only say whether
the pattern is more than this data would give by chance, and timing alone can't show why.
"""

from __future__ import annotations

import math
import random
import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Any

from backend.network.config import CoordinationConfig
from backend.network.coshare import CoShare, find_co_shares
from backend.network.dataset import Dataset, Post, format_timestamp

# Enough shuffles that a result below 0.05 is possible and is not one lucky draw.
MIN_PERMUTATIONS = 99
SIGNIFICANCE = 0.05
ABOVE_CHANCE = "above_chance"
NOT_ABOVE_CHANCE = "not_above_chance"
NOTHING_OBSERVED = "nothing_observed"
TEST_INCOMPLETE = "test_incomplete"
_MIN_BURST_BUCKETS = 10
_MIN_BURST_POSTS = 5
_MIN_BURST_ACCOUNTS = 3
_BURST_SPREAD = 5.0
_MAD_TO_SD = 1.4826
_BASELINE_EXPLAINS = 0.7


def repeated_pairs(co_shares: dict[tuple[str, str], CoShare], config: CoordinationConfig) -> int:
    return sum(1 for pair in co_shares.values() if pair.distinct_items >= config.min_shared_items)


def permutation_test(
    posts: Iterable[Post],
    config: CoordinationConfig,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Shuffle post times between posts and count how often chance matches what was observed.

    Who posted what, how much each account posted and when activity happened all stay as
    they were, so a news event everyone posts about at once stays in the shuffled data too.
    Only the link between a particular post and a particular moment is broken.
    """
    posts = list(posts)
    observed = repeated_pairs(find_co_shares(posts, config), config)
    base = {"statistic": "account pairs repeatedly posting the same items close in time", "observed": observed}
    if observed == 0:
        return {
            **base,
            "verdict": NOTHING_OBSERVED,
            "permutations": 0,
            "p_value": None,
            "chance_mean": None,
            "chance_max": None,
            "reason": "No pair of accounts repeatedly posted the same items close in time, so there was nothing to test.",
        }
    rng = random.Random(config.null_test_seed)
    times = [post.created_at for post in posts]
    limit = clock() + config.null_test_max_seconds
    counts: list[int] = []
    for _ in range(config.null_test_permutations):
        if clock() > limit:
            break
        rng.shuffle(times)
        shuffled = [replace(post, created_at=moment) for post, moment in zip(posts, times)]
        counts.append(repeated_pairs(find_co_shares(shuffled, config), config))
    result = {
        **base,
        "permutations": len(counts),
        "chance_mean": round(statistics.fmean(counts), 2) if counts else None,
        "chance_max": max(counts, default=None),
    }
    if len(counts) < MIN_PERMUTATIONS:
        return {
            **result,
            "verdict": TEST_INCOMPLETE,
            "p_value": None,
            "reason": f"Only {len(counts)} shuffles finished in the time allowed, too few for a result.",
        }
    # The +1s count the observed data as one possible shuffle, so this can never report 0.
    p_value = round((1 + sum(count >= observed for count in counts)) / (len(counts) + 1), 4)
    if p_value < SIGNIFICANCE:
        return {
            **result,
            "verdict": ABOVE_CHANCE,
            "p_value": p_value,
            "reason": (
                f"{observed} repeating pairs were seen. With the timing shuffled there were {result['chance_mean']} on "
                f"average and at most {result['chance_max']}, so timing this close is unlikely to be chance in this data. "
                "That doesn't show why it happened."
            ),
        }
    return {
        **result,
        "verdict": NOT_ABOVE_CHANCE,
        "p_value": p_value,
        "reason": (
            f"{observed} repeating pairs were seen, but shuffling the timing gave {result['chance_mean']} on average and "
            f"up to {result['chance_max']}. This is what these posts could give by chance, so no signal was found."
        ),
    }


def activity_baseline(dataset: Dataset, flagged_members: set[str]) -> dict[str, Any] | None:
    """Ask whether simply picking the busiest accounts would have found the same ones."""
    if not flagged_members:
        return None
    counts: dict[str, int] = defaultdict(int)
    for post in dataset.posts:
        counts[post.account_id] += 1
    top = {account for account, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[: len(flagged_members)]}
    overlap = round(len(top & flagged_members) / len(flagged_members), 3)
    flagged_counts = [counts[member] for member in flagged_members]
    others = [count for account, count in counts.items() if account not in flagged_members]
    explains = overlap >= _BASELINE_EXPLAINS and len(others) > 0
    return {
        "flagged_accounts": len(flagged_members),
        "overlap_with_busiest": overlap,
        "median_posts_flagged": statistics.median(flagged_counts),
        "median_posts_others": statistics.median(others) if others else None,
        "activity_could_explain": explains,
        "reason": (
            f"{overlap:.0%} of the flagged accounts are also among the same number of busiest accounts, so how much "
            "they post could account for much of this."
            if explains
            else f"Only {overlap:.0%} of the flagged accounts are among the busiest, so post volume alone doesn't explain this."
            if others
            else "Every account in this data was flagged, so there's nothing to compare post volume with."
        ),
    }


def find_bursts(posts: Iterable[Post], config: CoordinationConfig) -> dict[str, Any]:
    """Find moments with far more posts than usual here. People also post together after real news."""
    posts = sorted(posts, key=lambda post: post.created_at)
    if not posts:
        return {"status": "not_applicable", "reason": "No posts were available.", "bursts": []}
    size = config.timeline_bucket_seconds
    start = posts[0].created_at.timestamp()
    buckets = math.floor((posts[-1].created_at.timestamp() - start) / size) + 1
    if buckets < _MIN_BURST_BUCKETS:
        return {
            "status": "not_applicable",
            "reason": f"These posts span too little time to define a usual rate (under {_MIN_BURST_BUCKETS} intervals).",
            "bursts": [],
        }
    grouped: dict[int, list[Post]] = defaultdict(list)
    for post in posts:
        grouped[math.floor((post.created_at.timestamp() - start) / size)].append(post)
    # Bursts this large are capped, as a very long span would otherwise cost memory for empty intervals.
    empties = max(0, buckets - len(grouped))
    counts = sorted([len(group) for group in grouped.values()] + [0] * empties)
    median = statistics.median(counts)
    spread = statistics.median(abs(count - median) for count in counts) * _MAD_TO_SD
    threshold = max(_MIN_BURST_POSTS, median + _BURST_SPREAD * max(spread, 1.0))
    bursts = []
    for index, group in sorted(grouped.items()):
        accounts = {post.account_id for post in group}
        if len(group) >= threshold and len(accounts) >= _MIN_BURST_ACCOUNTS:
            bursts.append(
                {
                    "start": format_timestamp(group[0].created_at),
                    "interval_seconds": size,
                    "posts": len(group),
                    "accounts": len(accounts),
                    "usual_posts_per_interval": median,
                    "index": index,
                }
            )
    return {"status": "complete", "reason": None, "threshold": threshold, "bursts": bursts[:20]}


def _hamming(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def link_fingerprints(posts: Iterable[Post], max_distance: int) -> tuple[list[Post], list[dict[str, Any]]]:
    """Treat near-identical image fingerprints as one image, so re-encoded copies still match.

    Fingerprints arrive from media analysis or a dataset, so a malformed one is ignored.
    """
    posts = list(posts)
    values: dict[str, int] = {}
    for post in posts:
        if post.media_fingerprint:
            try:
                values[post.media_fingerprint] = int(post.media_fingerprint, 16)
            except ValueError:
                continue
    names = sorted(values)
    parent = {name: name for name in names}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            if _hamming(values[left], values[right]) <= max_distance:
                parent[find(right)] = find(left)

    members: dict[str, list[Post]] = defaultdict(list)
    for post in posts:
        if post.media_fingerprint in values:
            members[find(post.media_fingerprint)].append(post)
    linked: dict[str, str] = {}
    groups = []
    for root, group in sorted(members.items()):
        accounts = {post.account_id for post in group}
        if len(accounts) < 2:
            continue
        key = f"fingerprint:{root}"
        linked.update({post.id: key for post in group})
        groups.append(
            {
                "fingerprint": root,
                "posts": len(group),
                "accounts": len(accounts),
                "variants": len({post.media_fingerprint for post in group}),
                "first_seen": format_timestamp(min(post.created_at for post in group)),
            }
        )
    updated = [replace(post, media_hash=linked[post.id]) if post.id in linked else post for post in posts]
    return updated, sorted(groups, key=lambda item: -item["accounts"])[:20]


def significance_checks(tests: dict[str, Any], synthetic: bool) -> list[dict[str, Any]]:
    """Describe the tests in the shared check format."""
    prefix = "Synthetic demo data. " if synthetic else ""
    limits = ["This describes patterns in the posts collected. It doesn't show that accounts are coordinating."]
    null = tests["null_test"]
    results = {
        ABOVE_CHANCE: f"More than chance in this data (p = {null.get('p_value')}, {null.get('permutations')} shuffles).",
        NOT_ABOVE_CHANCE: f"No signal: chance gives this too (p = {null.get('p_value')}, {null.get('permutations')} shuffles).",
        NOTHING_OBSERVED: "Nothing to test.",
        TEST_INCOMPLETE: "No result.",
    }
    checks = [
        {
            "check_id": "network.null_test",
            "module": "network",
            "label": "Comparison with shuffled timing",
            "status": "complete" if null["verdict"] != TEST_INCOMPLETE else "unavailable",
            "result": prefix + results[null["verdict"]],
            "reasoning": null["reason"],
            "limitations": [*limits, "Only post timing is shuffled. A shared cause, such as a news story, can also pass this test."],
        }
    ]
    bursts = tests["bursts"]
    checks.append(
        {
            "check_id": "network.bursts",
            "module": "network",
            "label": "Sudden bursts",
            "status": bursts["status"],
            "result": prefix + (f"{len(bursts['bursts'])} burst(s) found." if bursts["status"] == "complete" else "Not measured."),
            "reasoning": bursts["reason"] or "Compared each interval with this data's usual rate of posts.",
            "limitations": [*limits, "Real news also causes bursts of posts."],
        }
    )
    media = tests["repeated_media"]
    checks.append(
        {
            "check_id": "network.repeated_media",
            "module": "network",
            "label": "Repeated media",
            "status": media["status"],
            "result": prefix + (f"{len(media['groups'])} image(s) reused by several accounts." if media["status"] == "complete" else "Not measured."),
            "reasoning": media["reason"] or "Near-identical image fingerprints are treated as one image.",
            "limitations": [*limits, "People often reuse the same image for ordinary reasons."],
        }
    )
    baseline = tests["activity_baseline"]
    if baseline:
        checks.append(
            {
                "check_id": "network.activity_baseline",
                "module": "network",
                "label": "Comparison with post counts",
                "status": "complete",
                "result": prefix + f"{baseline['overlap_with_busiest']:.0%} of flagged accounts are among the busiest.",
                "reasoning": baseline["reason"],
                "limitations": limits,
            }
        )
    # The shared format of network checks: nothing here is benchmarked, and a status is said in the result.
    return [{**{k: v for k, v in check.items() if k != "status"}, "benchmark": None, "artifacts": []} for check in checks]
