"""Trace how submitted content spread across the public platforms we can read.

Search results are only candidates. A post counts only if it really carries the
link, hashtag or phrase searched for, and only the platforms read are ever
described as covered.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.network.analysis import NetworkAnalysis, analyze_network
from backend.network.config import CoordinationConfig
from backend.network.coshare import find_co_shares, normalize_text, normalize_url
from backend.network.dataset import format_timestamp, parse_dataset, parse_timestamp
from backend.network.sources import (
    NOT_CONNECTED,
    Budgeted,
    Fetch,
    FetchError,
    PublicPost,
    SearchQuery,
    Source,
    default_sources,
    live_fetch,
)
from backend.network.sources.base import URL_IN_TEXT, safe_web_link

_TIME_BUDGET_SECONDS = 25
# Reading each co-posting account's history costs a request, so it's capped.
_MAX_ACCOUNTS_EXPANDED = 20

_LIMITATIONS = [
    "Coverage is partial: only the platforms listed were read, and public search doesn't return every post.",
    "Finding no posts doesn't show the content wasn't shared elsewhere or in private channels.",
    "Accounts on different platforms are never treated as the same person.",
]

_NOTHING_TO_SEARCH = (
    "Nothing to search for: public platforms can't be searched by an image alone, so this "
    "needs text, a link or a hashtag, such as page links from a web source search."
)


@dataclass(frozen=True)
class TraceResult:
    analysis: NetworkAnalysis
    module_result: dict[str, Any]
    coverage: dict[str, Any]


@dataclass
class Collected:
    posts: dict[str, PublicPost] = field(default_factory=dict)
    on_topic: dict[str, str] = field(default_factory=dict)
    platforms: list[dict[str, Any]] = field(default_factory=list)
    histories_read: set[str] = field(default_factory=set)
    histories_failed: int = 0
    histories_skipped: int = 0


def matched_on(post: PublicPost, query: SearchQuery) -> str | None:
    """Say what ties this post to the query, or None if the search result was only fuzzy."""
    wanted = {normalize_url(url) for url in query.urls} - {None}
    linked = {normalize_url(link) for link in [post.url, *URL_IN_TEXT.findall(post.text)] if link}
    if wanted & linked:
        return "link"
    if set(query.hashtags) & set(post.hashtags):
        return "hashtag"
    text = f" {normalize_text(post.text)} "
    if any(f" {phrase} " in text for phrase in query.phrases):
        return "text"
    return None


def collect(
    query: SearchQuery, sources: Iterable[Source], fetch: Fetch, collected: Collected | None = None
) -> Collected:
    """Search each source and keep the posts that really match, reporting what happened.

    Pass an earlier ``collected`` to add to it, as monitoring does between polls.
    """
    collected = collected or Collected()
    collected.platforms = []
    for source in sources:
        outcome = source.search(query, fetch)
        new_matches = 0
        for post in outcome.posts:
            match = matched_on(post, query)
            if match is None:
                continue
            collected.posts[post.id] = post
            if post.id not in collected.on_topic:
                collected.on_topic[post.id] = match
                new_matches += 1
        if outcome.failures and outcome.searches_run == len(outcome.failures):
            status = "failed"
        elif outcome.failures:
            status = "partial"
        elif outcome.searches_run:
            status = "searched"
        else:
            status = "not_searchable"
        collected.platforms.append(
            {
                "platform": source.platform,
                "label": source.label,
                "status": status,
                "searches_run": outcome.searches_run,
                "matching_posts": sum(
                    1 for post_id in collected.on_topic if collected.posts[post_id].platform == source.platform
                ),
                "new_matching_posts": new_matches,
                "results_returned": len(outcome.posts),
                "malformed_records_skipped": outcome.malformed,
                "notes": [*dict.fromkeys(outcome.failures), *outcome.unsupported],
            }
        )
    return collected


def build_raw_dataset(
    case_id: str,
    posts: Iterable[PublicPost],
    on_topic: dict[str, str],
    synthetic: bool = False,
) -> dict[str, Any]:
    """Turn collected posts into the dataset format the engine reads."""
    accounts: dict[str, dict[str, Any]] = {}
    records = []
    for post in posts:
        known = accounts.setdefault(post.author_id, {"id": post.author_id, "handle": post.author_handle, "followers": 0})
        known["followers"] = max(known["followers"], post.followers)
        for account_id, handle in post.mentions:
            accounts.setdefault(account_id, {"id": account_id, "handle": handle, "followers": 0})
        records.append(
            {
                "id": post.id,
                "account_id": post.author_id,
                "created_at": post.created_at,
                "text": post.text,
                "url": post.url,
                "mentions": [account_id for account_id, _ in post.mentions],
                "platform": post.platform,
                "on_topic": post.id in on_topic,
            }
        )
    return {
        "metadata": {"case_id": case_id, "synthetic": synthetic},
        "accounts": list(accounts.values()),
        "posts": records,
    }


def _expand_co_posting_accounts(
    collected: Collected,
    sources: Iterable[Source],
    fetch: Fetch,
    config: CoordinationConfig,
) -> None:
    """Read the other posts of accounts that posted close together.

    Searching for one item can only ever find one shared item, while the engine
    needs repetition. So the histories of co-posting accounts are read to see
    whether they repeatedly post the same things. Each is read once, and a failed
    read is tried again on the next poll.
    """
    raw = build_raw_dataset("expansion", collected.posts.values(), collected.on_topic)
    pairs = find_co_shares(parse_dataset(raw).posts, config)
    co_posting = sorted({account for pair in pairs for account in pair})
    by_platform = {source.platform: source for source in sources}
    one_post_per_author = {post.author_id: post for post in collected.posts.values()}

    pending = [account for account in co_posting if account not in collected.histories_read]
    allowed = max(0, _MAX_ACCOUNTS_EXPANDED - len(collected.histories_read))
    collected.histories_failed = 0
    collected.histories_skipped = max(0, len(pending) - allowed)
    for account_id in pending[:allowed]:
        post = one_post_per_author.get(account_id)
        source = by_platform.get(post.platform) if post else None
        if post is None or source is None:
            continue
        try:
            for extra in source.author_posts(post, fetch):
                collected.posts.setdefault(extra.id, extra)
            collected.histories_read.add(account_id)
        except FetchError:
            collected.histories_failed += 1


def _spread(collected: Collected, synthetic: bool) -> list[dict[str, Any]]:
    """List the matching posts in time order, naming the earliest found, not an origin."""
    ordered = sorted(
        (collected.posts[post_id] for post_id in collected.on_topic),
        key=lambda post: (parse_timestamp(post.created_at), post.id),
    )
    return [
        {
            "order": index,
            "platform": post.platform,
            "account_id": post.author_id,
            "handle": post.author_handle,
            "posted_at": format_timestamp(parse_timestamp(post.created_at)),
            # Invented posts have no real page, and a link could land on someone else's.
            "permalink": None if synthetic else safe_web_link(post.permalink),
            "matched_on": collected.on_topic[post.id],
            "earliest_found": index == 1,
        }
        for index, post in enumerate(ordered, start=1)
    ]


def _module_result(
    analysis: NetworkAnalysis,
    collected: Collected,
    query: SearchQuery,
    synthetic: bool,
) -> dict[str, Any]:
    reachable = [item for item in collected.platforms if item["status"] in ("searched", "partial")]
    missing = ", ".join(sorted(NOT_CONNECTED))
    limitations = [*_LIMITATIONS, f"Not connected: {missing}."]

    if query.is_empty():
        return {
            "status": "unavailable",
            "score": None,
            "confidence": None,
            "evidence": [],
            "limitations": [_NOTHING_TO_SEARCH, *limitations],
        }
    if not reachable:
        return {
            "status": "unavailable",
            "score": None,
            "confidence": None,
            "evidence": [],
            "limitations": ["No platform could be searched for this content.", *limitations],
        }

    per_platform = "; ".join(f"{item['label']}: {item['matching_posts']} matching" for item in collected.platforms)
    coverage_line = f"{'Replayed synthetic posts' if synthetic else 'Searched public posts'}. {per_platform}."
    if not collected.on_topic:
        return {
            "status": "complete",
            "score": None,
            "confidence": None,
            "evidence": [coverage_line],
            "limitations": [
                "Inconclusive: no matching public posts were found, so no spread could be traced.",
                *limitations,
            ],
        }

    result = analysis.module_result
    first_lines = [line for line in result["evidence"] if line.startswith("SYNTHETIC")] if synthetic else []
    other_lines = [line for line in result["evidence"] if line not in first_lines]
    history_line = (
        f"To check for repetition, the other recent public posts of {len(collected.histories_read)} accounts "
        "that posted this content close together were also read."
    )
    history_lines = [history_line] if collected.histories_read else []
    return {
        **result,
        "evidence": [*first_lines, coverage_line, *history_lines, *other_lines],
        "limitations": [*result["limitations"], *limitations],
    }


def assemble_result(
    case_id: str,
    collected: Collected,
    query: SearchQuery,
    sources: Iterable[Source],
    fetch: Fetch,
    config: CoordinationConfig,
    now: datetime | None = None,
) -> TraceResult:
    """Check co-posting accounts' histories, run the engine and report the coverage."""
    synthetic = getattr(fetch, "synthetic", False) is True
    _expand_co_posting_accounts(collected, sources, fetch, config)
    dataset = parse_dataset(build_raw_dataset(case_id, collected.posts.values(), collected.on_topic, synthetic))
    analysis = analyze_network(dataset, config)
    searched_at = getattr(fetch, "recorded_at", None) or format_timestamp(now or datetime.now(UTC))
    coverage = {
        "mode": getattr(fetch, "mode", "live"),
        "searched_at": searched_at,
        "synthetic": synthetic,
        "query": {"urls": list(query.urls), "phrases": list(query.phrases), "hashtags": list(query.hashtags)},
        "platforms": collected.platforms,
        "not_connected": [{"platform": name, "reason": reason} for name, reason in sorted(NOT_CONNECTED.items())],
        "account_histories": {
            "read": len(collected.histories_read),
            "failed": collected.histories_failed,
            "skipped_by_cap": collected.histories_skipped,
        },
        "spread": _spread(collected, synthetic),
    }
    return TraceResult(analysis, _module_result(analysis, collected, query, synthetic), coverage)


def trace_public_spread(
    case_id: str,
    *,
    text: str | None = None,
    url: str | None = None,
    urls: tuple[str, ...] = (),
    hashtags: tuple[str, ...] = (),
    sources: list[Source] | None = None,
    fetch: Fetch = live_fetch,
    config: CoordinationConfig | None = None,
    now: datetime | None = None,
) -> TraceResult:
    """Find public posts of the submitted content and analyze how they spread.

    ``urls`` is for pages found by a web source search. An image alone can't be
    searched for on these platforms, so it gives an ``unavailable`` result.
    """
    config = config or CoordinationConfig()
    sources = default_sources() if sources is None else sources
    query = SearchQuery.from_submission(text=text, url=url, urls=urls, hashtags=hashtags)
    budgeted = Budgeted(fetch, _TIME_BUDGET_SECONDS)
    collected = collect(query, sources, budgeted) if not query.is_empty() else Collected()
    return assemble_result(case_id, collected, query, sources, budgeted, config, now)
