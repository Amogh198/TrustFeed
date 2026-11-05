"""Bluesky, page links, repost counts, explanation checks and watch limits. No network is used."""

import json
from urllib.parse import quote

import pytest

from backend.network import (
    DEMO_CASE_ID,
    DEMO_STORY_CASE_ID,
    WatchError,
    build_network_checks,
    get_network_checks,
    list_watches,
    poll_watch,
    start_watch,
    stop_watch,
    trace_case,
    trace_public_spread,
)
from backend.network.sources import (
    BlueskySource,
    FetchError,
    MastodonSource,
    PublicPost,
    SearchQuery,
)
from backend.network.sources import __dict__ as sources_module
from backend.network.trace import matched_on
from backend.network.watches import (
    MAX_WATCHES,
    MIN_POLL_INTERVAL_SECONDS,
    WATCH_LIFETIME_SECONDS,
)

ITEM = "https://story.example/flood"
PAGE = "https://pages.example/gallery"
SEARCH = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
FEED = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
CHECK_FIELDS = {"check_id", "module", "label", "result", "reasoning", "benchmark", "artifacts", "limitations"}


def link_search(url):
    return f"{SEARCH}?q=*&url={quote(url, safe='')}&sort=latest&limit=100"


def view(number, url: str | None = ITEM, seconds=0, text="A shared story about the flood", **extra):
    return {
        "uri": f"at://did:plc:u{number}/app.bsky.feed.post/{number}",
        "indexedAt": f"2026-03-01T09:00:{seconds:02d}.000Z",
        "author": {"did": f"did:plc:u{number}", "handle": f"u{number}.example"},
        "record": {
            "text": text,
            "createdAt": "2020-01-01T00:00:00Z",
            "embed": {"external": {"uri": url}} if url else {},
        },
        "repostCount": 3,
        **extra,
    }


class Fake:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url in self.responses:
            return self.responses[url]
        if "/timelines/link" in url:
            raise FetchError("The platform refused the request (HTTP 404)", 404)
        raise FetchError("The platform refused the request (HTTP 403)", 403)


def post(**fields):
    return PublicPost(platform="p", id="1", author_id="a", author_handle="a", author_ref="a", created_at="2026-01-01T00:00:00+00:00", **fields)


# Bluesky


def bluesky_search(*views, url=ITEM):
    return BlueskySource().search(SearchQuery(urls=(url,)), Fake({link_search(url): {"posts": list(views)}}))


def test_bluesky_reads_link_author_time_and_reposts():
    found = bluesky_search(view(1)).posts[0]
    assert found.url == ITEM
    assert found.author_id == "bluesky:did:plc:u1"
    assert found.author_handle == "u1.example"
    assert found.permalink == "https://bsky.app/profile/u1.example/post/1"
    assert found.repost_count == 3
    # The server's time, as the poster's app can claim any createdAt.
    assert found.created_at.startswith("2026-03-01T09:00:00")


def test_bluesky_reads_facet_links_hashtags_and_mentions():
    record_view = view(1, url=None)
    record_view["record"]["facets"] = [
        {"features": [{"$type": "app.bsky.richtext.facet#link", "uri": ITEM}]},
        {"features": [{"$type": "app.bsky.richtext.facet#tag", "tag": "FloodAlert"}]},
        {"features": [{"$type": "app.bsky.richtext.facet#mention", "did": "did:plc:v"}]},
    ]
    found = bluesky_search(record_view).posts[0]
    assert found.url == ITEM
    assert found.hashtags == ("floodalert",)
    assert found.mentions == (("bluesky:did:plc:v", "did:plc:v"),)


def test_bluesky_respects_accounts_that_hide_from_logged_out_viewers():
    hidden = view(1)
    hidden["author"]["labels"] = [{"val": "!no-unauthenticated"}]
    assert bluesky_search(hidden, view(2)).posts[0].author_ref == "did:plc:u2"
    assert len(bluesky_search(hidden, view(2)).posts) == 1


def test_bluesky_counts_broken_records_and_survives_odd_responses():
    bad_text = view(2)
    bad_text["record"]["text"] = 5
    outcome = bluesky_search(view(1), {"uri": "x"}, bad_text)
    assert len(outcome.posts) == 1
    assert outcome.malformed == 2
    for odd in (["a list"], "text", None, {"posts": "text"}):
        assert BlueskySource().search(SearchQuery(urls=(ITEM,)), Fake({link_search(ITEM): odd})).posts == []


def test_bluesky_failure_is_reported():
    outcome = BlueskySource().search(SearchQuery(urls=(ITEM,)), Fake())
    assert outcome.failures == ["The platform refused the request (HTTP 403)"]


def test_bluesky_searches_tags_and_quoted_phrases_with_encoding():
    fetch = Fake()
    BlueskySource().search(SearchQuery(hashtags=("a&b=c",), phrases=("the dam failed",)), fetch)
    assert fetch.calls == [
        f"{SEARCH}?q=*&tag=a%26b%3Dc&sort=latest&limit=100",
        f"{SEARCH}?q=%22the%20dam%20failed%22&sort=latest&limit=100",
    ]


def test_bluesky_history_leaves_out_reposts():
    subject = bluesky_search(view(1)).posts[0]
    address = f"{FEED}?actor=did%3Aplc%3Au1&filter=posts_no_replies&limit=100"
    feed = {"feed": [{"post": view(1, url="https://a.example/1")}, {"post": view(9), "reason": {"$type": "repost"}}]}
    assert [item.url for item in BlueskySource().author_posts(subject, Fake({address: feed}))] == ["https://a.example/1"]


def test_bluesky_counts_as_connected_and_others_stay_listed():
    assert "BlueskySource" in sources_module
    coverage = trace_public_spread("case-b", url=ITEM, fetch=Fake({link_search(ITEM): {"posts": [view(1)]}})).coverage
    assert "bluesky" not in {item["platform"] for item in coverage["not_connected"]}
    assert {"reddit", "youtube", "x", "private channels"} <= {item["platform"] for item in coverage["not_connected"]}
    assert next(item for item in coverage["platforms"] if item["platform"] == "bluesky")["matching_posts"] == 1


# Mastodon links


def masto_status(index=1, **overrides):
    return {
        "uri": f"https://social.example/s/{index}",
        "url": f"https://social.example/@u/{index}",
        "created_at": "2026-03-01T09:00:00Z",
        "visibility": "public",
        "reblog": None,
        "content": "<p>Text</p>",
        "card": {"url": ITEM},
        "reblogs_count": 4,
        "account": {"id": "1", "acct": "u"},
        **overrides,
    }


MASTODON_LINK = f"https://mastodon.social/api/v1/timelines/link?url={quote(ITEM, safe='')}&limit=40"


def test_trending_link_is_found_on_mastodon_and_the_limit_is_stated():
    outcome = MastodonSource().search(SearchQuery(urls=(ITEM,)), Fake({MASTODON_LINK: [masto_status()]}))
    assert outcome.searches_run == 1
    assert outcome.posts[0].url == ITEM
    assert outcome.posts[0].repost_count == 4
    assert "trending" in outcome.unsupported[0]


def test_a_link_that_is_not_trending_is_not_searchable_rather_than_a_failure():
    outcome = MastodonSource().search(SearchQuery(urls=(ITEM,)), Fake())
    assert outcome.searches_run == 0
    assert outcome.failures == []
    coverage = trace_public_spread("case-m", url=ITEM, fetch=Fake()).coverage
    row = next(item for item in coverage["platforms"] if item["platform"] == "mastodon")
    assert row["status"] == "not_searchable"


def test_other_mastodon_errors_on_a_link_are_failures():
    def refuse(_url):
        raise FetchError("The platform refused the request (HTTP 500)", 500)

    assert MastodonSource().search(SearchQuery(urls=(ITEM,)), refuse).failures


# Submitted links and page links


def test_query_keeps_page_links_apart_from_submitted_links():
    query = SearchQuery.from_submission(url=ITEM, urls=(PAGE, ITEM))
    assert query.urls == (ITEM,)
    assert query.page_urls == (PAGE,)
    assert query.all_urls == (ITEM, PAGE)


def test_page_only_query_is_not_empty():
    assert not SearchQuery.from_submission(urls=(PAGE,)).is_empty()


def test_matched_on_distinguishes_submitted_and_page_links():
    query = SearchQuery(urls=(ITEM,), page_urls=(PAGE,), phrases=("the dam has failed",))
    assert matched_on(post(url=ITEM), query) == "link"
    assert matched_on(post(url=PAGE), query) == "page_link"
    assert matched_on(post(url=PAGE, text="The dam has failed"), query) == "text"
    assert matched_on(post(url="https://x.example/", other_links=(PAGE,)), query) == "page_link"


def page_link_trace(case_id="case-p"):
    return trace_public_spread(
        case_id,
        url=ITEM,
        urls=(PAGE,),
        fetch=Fake({link_search(ITEM): {"posts": [view(1)]}, link_search(PAGE): {"posts": [view(2, url=PAGE, seconds=9)]}}),
    )


def test_coverage_and_evidence_word_page_link_matches_differently():
    result = page_link_trace()
    assert [item["matched_on"] for item in result.coverage["spread"]] == ["link", "page_link"]
    assert result.coverage["query"]["page_urls"] == [PAGE]
    assert any("1 of the matching posts link to a page" in line for line in result.module_result["evidence"])
    assert any("something else on that page" in line for line in result.module_result["evidence"])


def test_watched_links_count_as_submitted():
    query = SearchQuery.from_submission(watched_urls=(ITEM,))
    assert query.urls == (ITEM,)
    assert query.page_urls == ()


def test_repost_count_is_reported_and_absent_means_null():
    coverage = page_link_trace().coverage
    assert coverage["spread"][0]["repost_count"] == 3
    bad = view(1)
    bad["repostCount"] = "many"
    assert bluesky_search(bad).posts[0].repost_count is None


# Explanation checks


def assert_valid_checks(checks):
    json.dumps(checks)
    for check in checks:
        assert set(check) == CHECK_FIELDS
        assert check["module"] == "network"
        assert check["benchmark"] is None
        assert isinstance(check["result"], str)
        assert check["reasoning"]
        assert all(isinstance(line, str) for line in check["limitations"])
    assert len({check["check_id"] for check in checks}) == len(checks)


def by_id(checks):
    return {check["check_id"]: check for check in checks}


def test_unknown_case_has_no_checks():
    assert get_network_checks("no-such-case") is None


def test_demo_checks_say_nothing_was_searched():
    checks = get_network_checks(DEMO_CASE_ID)
    assert checks is not None
    assert_valid_checks(checks)
    found = by_id(checks)
    assert "synthetic" in found["network.platform_search"]["result"]
    assert "network.matching_posts" not in found
    assert found["network.coordination_signal"]["result"].startswith("Signal for review")


def test_story_checks_cover_search_posts_and_signal_and_label_synthetic():
    checks = get_network_checks(DEMO_STORY_CASE_ID)
    assert checks is not None
    assert_valid_checks(checks)
    found = by_id(checks)
    assert found["network.platform_search"]["result"].startswith("Replayed synthetic posts from 3 of 3")
    assert "earliest found" in found["network.matching_posts"]["result"]
    signal = found["network.coordination_signal"]
    assert "12 accounts" in signal["result"]
    assert any("does not establish intent" in line for line in signal["limitations"])
    assert signal["artifacts"] == [{"type": "network_graph", "route": f"/api/network/{DEMO_STORY_CASE_ID}"}]


def test_checks_never_call_anything_proof_or_the_source():
    for case_id in (DEMO_CASE_ID, DEMO_STORY_CASE_ID):
        checks = get_network_checks(case_id)
        assert checks is not None
        for check in checks:
            assert "is the source" not in check["result"]
            assert "the original" not in json.dumps(check)
            assert "bot" not in check["result"].lower().split()


def test_checks_for_no_group_say_inconclusive_and_not_absent():
    trace_case("case-c1", url=ITEM, fetch=Fake({link_search(ITEM): {"posts": [view(1)]}}))
    checks = get_network_checks("case-c1")
    assert checks is not None
    assert_valid_checks(checks)
    signal = by_id(checks)["network.coordination_signal"]
    assert signal["result"].startswith("Inconclusive")
    assert "does not show that coordination is absent" in signal["limitations"][0]


def test_checks_for_no_posts_are_inconclusive():
    trace_case("case-c2", url=ITEM, fetch=Fake({link_search(ITEM): {"posts": []}}))
    checks = get_network_checks("case-c2")
    assert checks is not None
    assert by_id(checks)["network.matching_posts"]["result"] == "No matching public posts were found."


def test_checks_when_nothing_could_be_searched_are_unavailable():
    trace_case("case-c3", url=ITEM, fetch=Fake())
    checks = get_network_checks("case-c3")
    assert checks is not None
    found = by_id(checks)
    assert found["network.coordination_signal"]["result"].startswith("Not available")
    assert "0 of" in found["network.platform_search"]["result"]


def test_page_link_matches_are_named_as_weaker_in_checks():
    result = page_link_trace("case-c4")
    checks = build_network_checks("case-c4", result.analysis.payload(), result.coverage, result.module_result)
    posts = by_id(checks)["network.matching_posts"]
    assert "something else on that page" in posts["reasoning"]
    assert any("weaker evidence" in line for line in posts["limitations"])


def test_hashtag_matches_are_named_as_topic_not_content():
    address = f"{SEARCH}?q=*&tag=flood&sort=latest&limit=100"
    tagged = view(1)
    tagged["record"]["facets"] = [{"features": [{"$type": "app.bsky.richtext.facet#tag", "tag": "flood"}]}]
    result = trace_public_spread("case-c6", hashtags=("flood",), fetch=Fake({address: {"posts": [tagged]}}))
    assert any("shared topic, not shared content" in line for line in result.module_result["evidence"])
    checks = build_network_checks("case-c6", result.analysis.payload(), result.coverage, result.module_result)
    assert any("shared topic" in line for line in by_id(checks)["network.matching_posts"]["limitations"])


def test_checks_can_be_built_from_stored_results_with_no_coverage():
    result = page_link_trace("case-c5")
    checks = build_network_checks("case-c5", result.analysis.payload(), None, result.module_result)
    assert by_id(checks)["network.platform_search"]["result"] == "No public-platform search ran for this case."


# Watch limits


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def no_leftover_watches():
    yield
    for watch_id in list_watches():
        stop_watch(watch_id)


def scripted():
    return Fake({link_search(ITEM): {"posts": [view(1)]}})


def test_a_watch_needs_opt_in_and_sends_nothing_when_refused():
    fetch = scripted()
    with pytest.raises(WatchError, match="opt-in"):
        start_watch("w", opted_in=False, urls=(ITEM,), fetch=fetch)
    assert fetch.calls == []
    assert list_watches() == []


def test_starting_a_watch_sends_nothing_until_polled():
    fetch = scripted()
    started = start_watch("w", opted_in=True, urls=(ITEM,), fetch=fetch)
    assert fetch.calls == []
    assert started["min_poll_interval_seconds"] == MIN_POLL_INTERVAL_SECONDS
    assert poll_watch("w")["total_matching_posts"] == 1
    assert fetch.calls


def test_polling_too_soon_is_refused_and_allowed_after_the_interval():
    clock = Clock()
    fetch = scripted()
    start_watch("w", opted_in=True, urls=(ITEM,), fetch=fetch, clock=clock)
    poll_watch("w", clock)
    calls = len(fetch.calls)
    with pytest.raises(WatchError, match="too soon"):
        poll_watch("w", clock)
    assert len(fetch.calls) == calls
    clock.now += MIN_POLL_INTERVAL_SECONDS
    assert poll_watch("w", clock)["poll"] == 2


def test_number_of_watches_is_limited():
    for number in range(MAX_WATCHES):
        start_watch(f"w{number}", opted_in=True, urls=(ITEM,), fetch=scripted())
    with pytest.raises(WatchError, match="At most"):
        start_watch("extra", opted_in=True, urls=(ITEM,), fetch=scripted())


def test_duplicate_and_empty_watches_are_refused():
    start_watch("w", opted_in=True, urls=(ITEM,), fetch=scripted())
    with pytest.raises(WatchError, match="already running"):
        start_watch("w", opted_in=True, urls=(ITEM,), fetch=scripted())
    with pytest.raises(WatchError, match="needs text"):
        start_watch("empty", opted_in=True, fetch=scripted())


def test_stopped_and_expired_watches_cannot_be_polled():
    clock = Clock()
    start_watch("a", opted_in=True, urls=(ITEM,), fetch=scripted(), clock=clock)
    assert stop_watch("a") is True
    assert stop_watch("a") is False
    with pytest.raises(WatchError, match="No such watch"):
        poll_watch("a", clock)
    start_watch("b", opted_in=True, urls=(ITEM,), fetch=scripted(), clock=clock)
    clock.now += WATCH_LIFETIME_SECONDS + 1
    with pytest.raises(WatchError, match="No such watch"):
        poll_watch("b", clock)
    assert list_watches(clock) == []
