"""Adapters and tracing. Offline: responses copy each platform's format with invented data."""

import json
import urllib.error
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest

from backend.network import (
    get_network_clusters,
    get_network_coverage,
    get_network_module_result,
    get_network_payload,
    trace_case,
    trace_public_spread,
)
from backend.network.sources import (
    Budgeted,
    FetchError,
    HackerNewsSource,
    LemmySource,
    MastodonSource,
    PublicPost,
    RecordingFetch,
    ReplayFetch,
    SearchQuery,
)
from backend.network.sources import fetching as fetching_module
from backend.network.trace import matched_on

START = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
ITEM = "https://story.example/flood"
LEMMY_SEARCH = "https://lemmy.world/api/v3/search?q={q}&type_={kind}&listing_type=All&sort=New&limit=50"
HN_BASE = "https://hn.algolia.com/api/v1/search_by_date"


def at(seconds):
    return (START + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def mastodon_status(index=1, seconds=0, content="<p>Hello</p>", **overrides):
    status = {
        "id": str(index),
        "uri": f"https://social.example/users/u{index}/statuses/{index}",
        "url": f"https://social.example/@u{index}/{index}",
        "created_at": at(seconds),
        "visibility": "public",
        "reblog": None,
        "content": content,
        "card": None,
        "tags": [{"name": "FloodAlert"}],
        "mentions": [],
        "account": {"id": str(100 + index), "acct": f"u{index}", "followers_count": 7},
    }
    return {**status, **overrides}


def lemmy_view(account, post_id, seconds, url=ITEM, name="A shared story", **post):
    return {
        "post": {
            "ap_id": f"https://lemmy.example/post/{post_id}",
            "name": name,
            "url": url,
            "published": (START + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S"),
            **post,
        },
        "creator": {"name": account, "actor_id": f"https://lemmy.example/u/{account}"},
    }


def hn_hit(object_id, author, seconds, url: str | None = ITEM, title: str | None = "A shared story", **extra):
    return {"objectID": str(object_id), "author": author, "created_at": at(seconds), "title": title, "url": url, **extra}


def lemmy_url(term, kind="Url"):
    return LEMMY_SEARCH.format(q=quote(term, safe=""), kind=kind)


def hn_url(term):
    return f"{HN_BASE}?query={quote(term, safe='')}&restrictSearchableAttributes=url&tags=story&hitsPerPage=50"


def lemmy_user(account):
    return f"https://lemmy.world/api/v3/user?username={account}%40lemmy.example&sort=New&limit=50"


class FakeFetch:
    """Serve set responses, and count calls. Anything unset fails as a platform would."""

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


def ring_fetch(size=6, items=3):
    """Lemmy accounts posting the same links seconds apart, visible in their histories."""
    accounts = [f"ring{index}" for index in range(size)]
    urls = [ITEM, *[f"https://story.example/other{item}" for item in range(1, items)]]
    histories = {
        account: [
            lemmy_view(account, f"{account}-{item}", item * 7200 + index * 3, url=url)
            for item, url in enumerate(urls)
        ]
        for index, account in enumerate(accounts)
    }
    responses = {lemmy_url(ITEM): {"posts": [views[0] for views in histories.values()]}}
    responses |= {lemmy_user(account): {"posts": views} for account, views in histories.items()}
    responses[hn_url(ITEM)] = {"hits": []}
    return FakeFetch(responses)


# Building a search from a submission


def test_query_takes_links_hashtags_and_a_leading_phrase():
    query = SearchQuery.from_submission(
        text="BREAKING! The dam has failed near the city, share this now #FloodAlert #बाढ़ https://a.example/x",
        url="https://b.example/y",
        urls=("https://c.example/z",),
    )
    assert query.urls == ("https://b.example/y", "https://a.example/x")
    assert query.page_urls == ("https://c.example/z",)
    assert query.hashtags == ("floodalert", "बाढ़")
    assert query.phrases == ("breaking the dam has failed near the city share this now floodalert",)


def test_short_text_is_too_generic_to_search():
    assert SearchQuery.from_submission(text="Breaking news!").is_empty()
    assert SearchQuery.from_submission().is_empty()


# Adapters


def test_mastodon_reads_visible_text_link_mentions_and_hashtags():
    status = mastodon_status(
        content=(
            '<p>Read this <a href="https://story.example/flood?utm_source=x">https://story.example/flood</a> '
            '<a class="mention u-url" href="https://social.example/@v">@v</a> '
            '<a class="mention hashtag" href="https://social.example/tags/FloodAlert">#FloodAlert</a></p>'
        ),
        mentions=[{"acct": "v"}, {"acct": "w@other.example"}],
    )
    url = "https://mastodon.social/api/v1/timelines/tag/floodalert?limit=40"
    outcome = MastodonSource().search(SearchQuery(hashtags=("floodalert",)), FakeFetch({url: [status]}))
    post = outcome.posts[0]
    assert post.text == "Read this @v #FloodAlert"
    assert post.url == "https://story.example/flood?utm_source=x"
    assert post.hashtags == ("floodalert",)
    assert post.author_handle == "u1@mastodon.social"
    assert post.mentions == (("mastodon:v@mastodon.social", "v@mastodon.social"), ("mastodon:w@other.example", "w@other.example"))
    assert post.followers == 7


def test_mastodon_prefers_the_link_preview_url():
    status = mastodon_status(card={"url": "https://story.example/card"}, content='<a href="https://other.example/">x</a>')
    url = "https://mastodon.social/api/v1/timelines/tag/t?limit=40"
    outcome = MastodonSource().search(SearchQuery(hashtags=("t",)), FakeFetch({url: [status]}))
    assert outcome.posts[0].url == "https://story.example/card"


def test_mastodon_leaves_out_reposts_and_non_public_posts_and_counts_broken_records():
    statuses = [mastodon_status(1), mastodon_status(2, visibility="unlisted"), mastodon_status(3, reblog={"id": "9"}), {"id": "broken"}]
    url = "https://mastodon.social/api/v1/timelines/tag/t?limit=40"
    outcome = MastodonSource().search(SearchQuery(hashtags=("t",)), FakeFetch({url: statuses}))
    assert [post.author_ref for post in outcome.posts] == ["101"]
    assert outcome.malformed == 1


def test_mastodon_says_text_cannot_be_searched_and_links_only_when_trending():
    outcome = MastodonSource().search(SearchQuery(urls=(ITEM,), phrases=("some phrase here",)), FakeFetch())
    assert outcome.searches_run == 0
    assert "Text can't be searched" in outcome.unsupported[0]
    assert "trending" in outcome.unsupported[1]


def test_tag_with_url_characters_cannot_change_the_request_host_or_path():
    fetch = FakeFetch()
    MastodonSource().search(SearchQuery(hashtags=("a/../../evil?x=1",)), fetch)
    assert fetch.calls == ["https://mastodon.social/api/v1/timelines/tag/a%2F..%2F..%2Fevil%3Fx%3D1?limit=40"]


def test_lemmy_treats_a_timestamp_without_a_zone_as_utc_and_skips_removed_posts():
    views = [lemmy_view("a", 1, 0), lemmy_view("b", 2, 5, removed=True), lemmy_view("c", 3, 5, deleted=True), {"post": {}}]
    outcome = LemmySource().search(SearchQuery(urls=(ITEM,)), FakeFetch({lemmy_url(ITEM): {"posts": views}}))
    assert [post.author_handle for post in outcome.posts] == ["a@lemmy.example"]
    assert outcome.posts[0].created_at == "2026-03-01T09:00:00+00:00"
    assert outcome.malformed == 1


@pytest.mark.parametrize("bad_response", [["a list"], "text", None, {"posts": "text"}])
def test_unexpected_response_shapes_do_not_crash(bad_response):
    query = SearchQuery(urls=(ITEM,))
    assert LemmySource().search(query, FakeFetch({lemmy_url(ITEM): bad_response})).posts == []
    assert HackerNewsSource().search(query, FakeFetch({hn_url(ITEM): bad_response})).posts == []


def test_hacker_news_reads_stories_and_comments():
    phrase = "a long enough phrase"
    url = f"{HN_BASE}?query=%22a%20long%20enough%20phrase%22&tags=(story,comment)&hitsPerPage=50"
    comment = hn_hit(7, "pat", 0, url=None, title=None, comment_text='<p>a long enough phrase <a href="https://x.example/1">link</a></p>')
    post = HackerNewsSource().search(SearchQuery(phrases=(phrase,)), FakeFetch({url: {"hits": [comment]}})).posts[0]
    assert post.text == "a long enough phrase"
    assert post.url == "https://x.example/1"
    assert post.permalink == "https://news.ycombinator.com/item?id=7"


@pytest.mark.parametrize(
    "field",
    [{"url": 5}, {"title": 5}, {"author": 5}, {"author": None}, {"created_at": 5}, {"objectID": None, "author": ["x"]}],
)
def test_wrong_types_from_a_platform_count_as_malformed_and_do_not_stop_the_trace(field):
    good = hn_hit(1, "first", 0)
    fetch = FakeFetch({lemmy_url(ITEM): {"posts": []}, hn_url(ITEM): {"hits": [{**hn_hit(2, "broken", 5), **field}, good]}})
    result = trace_public_spread("case-1", url=ITEM, fetch=fetch)
    row = next(item for item in result.coverage["platforms"] if item["platform"] == "hackernews")
    assert row["malformed_records_skipped"] == 1
    assert [item["handle"] for item in result.coverage["spread"]] == ["first"]


def test_mastodon_wrong_types_count_as_malformed():
    url = "https://mastodon.social/api/v1/timelines/tag/t?limit=40"
    bad_link = mastodon_status(1, card={"url": 5})
    bad_account = mastodon_status(2, account={"id": "1", "acct": 5})
    outcome = MastodonSource().search(SearchQuery(hashtags=("t",)), FakeFetch({url: [bad_link, bad_account, mastodon_status(3)]}))
    assert outcome.malformed == 2
    assert len(outcome.posts) == 1


@pytest.mark.parametrize(
    ("permalink", "expected"),
    [
        ("https://social.example/@u1/1", "https://social.example/@u1/1"),
        ("http://social.example/@u1/1", "http://social.example/@u1/1"),
        ("javascript:alert(1)", None),
        (" JavaScript:alert(1)", None),
        ("data:text/html,x", None),
        ("http://[broken", None),
    ],
)
def test_only_web_links_are_returned_as_permalinks(permalink, expected):
    url = "https://mastodon.social/api/v1/timelines/tag/floodalert?limit=40"
    status = mastodon_status(url=permalink)
    fetch = FakeFetch({url: [status]})
    coverage = trace_public_spread("case-1", hashtags=("floodalert",), fetch=fetch).coverage
    assert coverage["spread"][0]["permalink"] == expected


# What counts as a match


def post_with(**fields):
    return PublicPost(platform="p", id="1", author_id="a", author_handle="a", author_ref="a", created_at=at(0), **fields)


def test_link_matches_across_tracking_scheme_and_www():
    query = SearchQuery(urls=("https://story.example/flood",))
    assert matched_on(post_with(url="http://www.story.example/flood/?utm_source=x&fbclid=1#top"), query) == "link"
    assert matched_on(post_with(text="see https://story.example/flood now"), query) == "link"


def test_fuzzy_search_results_are_dropped():
    query = SearchQuery(urls=("https://story.example/flood",), phrases=("the dam has failed",), hashtags=("floodalert",))
    assert matched_on(post_with(url="https://story.example/other", text="A dam failed somewhere"), query) is None
    assert matched_on(post_with(text="the dam has failedness"), query) is None


def test_phrase_and_hashtag_matches_are_named():
    query = SearchQuery(phrases=("the dam has failed",), hashtags=("floodalert",))
    assert matched_on(post_with(text="NEWS: The dam has failed!"), query) == "text"
    assert matched_on(post_with(hashtags=("floodalert",)), query) == "hashtag"


# Tracing


def test_repeated_co_sharing_is_found_through_account_histories():
    result = trace_public_spread("case-1", url=ITEM, fetch=ring_fetch())
    flagged = [cluster for cluster in result.analysis.clusters if cluster["flagged"]]
    assert len(flagged) == 1
    assert flagged[0]["size"] == 6
    assert result.module_result["status"] == "complete"
    assert result.module_result["score"] == flagged[0]["coordination_risk_score"]
    assert result.module_result["confidence"] is None
    assert result.coverage["account_histories"] == {"read": 6, "failed": 0, "skipped_by_cap": 0}
    assert any("other recent public posts of 6 accounts" in line for line in result.module_result["evidence"])


def test_co_posting_one_item_with_no_repetition_is_inconclusive_not_coordination():
    fetch = ring_fetch(items=1)
    result = trace_public_spread("case-1", url=ITEM, fetch=fetch)
    assert result.analysis.clusters == []
    assert result.module_result["score"] is None
    assert result.module_result["limitations"][0].startswith("Inconclusive")
    assert {edge["type"] for edge in result.analysis.edges} == {"weak_co_share"}


def test_spread_lists_matching_posts_in_order_with_earliest_found_wording():
    fetch = FakeFetch(
        {
            lemmy_url(ITEM): {"posts": [lemmy_view("later", 2, 900)]},
            hn_url(ITEM): {"hits": [hn_hit(1, "first", 0), hn_hit(2, "off-topic", 5, url="https://other.example/")]},
        }
    )
    coverage = trace_public_spread("case-1", url=ITEM, fetch=fetch).coverage
    assert [item["handle"] for item in coverage["spread"]] == ["first", "later@lemmy.example"]
    assert [item["earliest_found"] for item in coverage["spread"]] == [True, False]
    assert coverage["spread"][0]["matched_on"] == "link"
    assert coverage["spread"][0]["posted_at"] == "2026-03-01T09:00:00Z"
    assert "origin" not in json.dumps(coverage["spread"])


def test_uncoordinated_spread_still_gets_nodes_and_a_timeline():
    fetch = FakeFetch(
        {
            lemmy_url(ITEM): {"posts": [lemmy_view("later", 2, 900)]},
            hn_url(ITEM): {"hits": [hn_hit(1, "first", 0)]},
        }
    )
    analysis = trace_public_spread("case-1", url=ITEM, fetch=fetch).analysis
    assert [frame["new_account_ids"] for frame in analysis.timeline] == [["hackernews:first"], ["lemmy:https://lemmy.example/u/later"]]
    assert all(frame["synthetic"] is False for frame in analysis.timeline)
    assert all(node["appears_at"] for node in analysis.nodes)
    assert {node["role"] for node in analysis.nodes} == {"background"}


def test_every_trace_says_what_was_not_covered():
    result = trace_public_spread("case-1", url=ITEM, fetch=ring_fetch())
    missing = {item["platform"] for item in result.coverage["not_connected"]}
    assert {"reddit", "youtube", "x", "private channels"} <= missing
    limitations = " ".join(result.module_result["limitations"])
    assert "Not connected" in limitations
    assert "Coverage is partial" in limitations
    assert "does not establish intent" in limitations


def test_real_traces_are_not_labelled_synthetic():
    result = trace_public_spread("case-1", url=ITEM, fetch=ring_fetch())
    assert result.coverage["synthetic"] is False
    assert not any("SYNTHETIC" in line for line in result.module_result["evidence"])
    assert all(node["synthetic"] is False for node in result.analysis.nodes)


def test_accounts_on_different_platforms_stay_separate():
    fetch = FakeFetch(
        {
            lemmy_url(ITEM): {"posts": [lemmy_view("same", 2, 900)]},
            hn_url(ITEM): {"hits": [hn_hit(1, "same", 0)]},
        }
    )
    nodes = trace_public_spread("case-1", url=ITEM, fetch=fetch).analysis.nodes
    assert len({node["id"] for node in nodes}) == 2


def test_nothing_to_search_for_makes_no_requests_and_explains_why():
    fetch = FakeFetch()
    result = trace_public_spread("case-1", fetch=fetch)
    assert fetch.calls == []
    assert result.module_result["status"] == "unavailable"
    assert "image alone" in result.module_result["limitations"][0]


def test_every_platform_failing_is_unavailable_with_the_reason():
    result = trace_public_spread("case-1", url=ITEM, fetch=FakeFetch())
    assert result.module_result["status"] == "unavailable"
    assert result.module_result["score"] is None
    statuses = {item["platform"]: item["status"] for item in result.coverage["platforms"]}
    assert statuses == {"mastodon": "not_searchable", "lemmy": "failed", "hackernews": "failed", "bluesky": "failed"}
    lemmy = next(item for item in result.coverage["platforms"] if item["platform"] == "lemmy")
    assert "HTTP 403" in lemmy["notes"][0]


def test_one_platform_failing_is_reported_and_the_rest_still_count():
    fetch = FakeFetch({hn_url(ITEM): {"hits": [hn_hit(1, "first", 0)]}})
    result = trace_public_spread("case-1", url=ITEM, fetch=fetch)
    assert result.module_result["status"] == "complete"
    assert any("Lemmy (as seen from lemmy.world): 0 matching" in line for line in result.module_result["evidence"])
    assert len(result.coverage["spread"]) == 1


def test_finding_no_posts_is_inconclusive_not_a_clean_result():
    fetch = FakeFetch({lemmy_url(ITEM): {"posts": []}, hn_url(ITEM): {"hits": []}})
    result = trace_public_spread("case-1", url=ITEM, fetch=fetch)
    assert result.module_result["status"] == "complete"
    assert result.module_result["score"] is None
    assert result.module_result["limitations"][0].startswith("Inconclusive")


def test_a_failed_history_read_is_counted_and_does_not_stop_the_trace():
    fetch = ring_fetch(size=6)
    del fetch.responses[lemmy_user("ring0")]
    result = trace_public_spread("case-1", url=ITEM, fetch=fetch)
    assert result.coverage["account_histories"] == {"read": 5, "failed": 1, "skipped_by_cap": 0}


def test_history_reads_are_capped():
    result = trace_public_spread("case-1", url=ITEM, fetch=ring_fetch(size=25, items=1))
    assert result.coverage["account_histories"]["read"] == 20
    assert result.coverage["account_histories"]["skipped_by_cap"] == 5


def test_duplicate_results_are_counted_once():
    view = lemmy_view("a", 1, 0)
    fetch = FakeFetch({lemmy_url(ITEM): {"posts": [view, view]}, hn_url(ITEM): {"hits": []}})
    result = trace_public_spread("case-1", url=ITEM, fetch=fetch)
    assert len(result.coverage["spread"]) == 1
    assert result.coverage["platforms"][1]["matching_posts"] == 1


# Fetching


def test_time_budget_stops_further_requests():
    fetch = FakeFetch({"https://a.example/": 1})
    assert Budgeted(fetch, 60)("https://a.example/") == 1
    with pytest.raises(FetchError, match="time limit"):
        Budgeted(fetch, -1)("https://a.example/")


def test_live_fetch_only_reads_https():
    with pytest.raises(FetchError, match="HTTPS"):
        fetching_module.live_fetch("http://a.example/")
    with pytest.raises(FetchError, match="HTTPS"):
        fetching_module.live_fetch("file:///etc/passwd")


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (urllib.error.HTTPError("https://a.example/", 403, "no", None, None), "HTTP 403"),  # type: ignore[arg-type]
        (urllib.error.URLError("down"), "could not be reached"),
        (TimeoutError(), "could not be reached"),
    ],
)
def test_live_fetch_turns_errors_into_fetch_errors(monkeypatch, error, message):
    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(fetching_module.urllib.request, "urlopen", fail)
    with pytest.raises(FetchError, match=message):
        fetching_module.live_fetch("https://a.example/")


def test_recorded_run_replays_identically_offline(tmp_path):
    recorder = RecordingFetch(ring_fetch())
    live = trace_public_spread("case-1", url=ITEM, fetch=recorder)
    path = tmp_path / "recording.json"
    recorder.save(path, "2026-03-02T00:00:00Z")

    replay = ReplayFetch(path)
    replayed = trace_public_spread("case-1", url=ITEM, fetch=replay)
    assert replayed.analysis.payload() == live.analysis.payload()
    assert replayed.coverage["mode"] == "replay"
    assert replayed.coverage["searched_at"] == "2026-03-02T00:00:00Z"
    assert replayed.coverage["synthetic"] is False


def test_replay_treats_an_unrecorded_request_as_a_failure(tmp_path):
    path = tmp_path / "recording.json"
    path.write_text(json.dumps({"responses": {}}), encoding="utf-8")
    with pytest.raises(FetchError, match="not in the recording"):
        ReplayFetch(path)("https://a.example/")


# The service


def test_traced_case_is_available_through_the_existing_getters():
    module_result = trace_case("traced-1", url=ITEM, fetch=ring_fetch())
    assert module_result == get_network_module_result("traced-1")
    payload = get_network_payload("traced-1")
    assert payload is not None
    assert set(payload) == {"nodes", "edges", "timeline"}
    json.dumps(payload)
    assert get_network_clusters("traced-1")
    coverage = get_network_coverage("traced-1")
    assert coverage is not None
    assert coverage["spread"]


def test_callers_cannot_corrupt_a_traced_case():
    trace_case("traced-2", url=ITEM, fetch=ring_fetch())
    coverage = get_network_coverage("traced-2")
    assert coverage is not None
    coverage["spread"].clear()
    again = get_network_coverage("traced-2")
    assert again is not None
    assert again["spread"]


def test_trace_case_does_not_accept_internal_arguments():
    with pytest.raises(TypeError):
        trace_case("traced-3", url=ITEM, sources=[])  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        trace_case("traced-3", url=ITEM, config=None)  # type: ignore[call-arg]


def test_demo_case_cannot_be_overwritten_by_a_trace():
    with pytest.raises(ValueError, match="reserved"):
        trace_case("demo-001", url=ITEM, fetch=ring_fetch())
    assert get_network_coverage("demo-001") is None


def test_oldest_traced_cases_are_dropped():
    fetch = FakeFetch({lemmy_url(ITEM): {"posts": []}, hn_url(ITEM): {"hits": []}})
    for index in range(130):
        trace_case(f"bulk-{index}", url=ITEM, fetch=fetch)
    assert get_network_payload("bulk-0") is None
    assert get_network_payload("bulk-129") is not None
