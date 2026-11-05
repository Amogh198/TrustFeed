"""Polling two or more platforms, and the offline linked demo story. No network is used."""

import json
from datetime import UTC, datetime
from urllib.parse import quote

import pytest

from backend.network import (
    DEMO_STORY_CASE_ID,
    Monitor,
    get_demo_story,
    get_network_clusters,
    get_network_coverage,
    get_network_module_result,
    get_network_payload,
    trace_case,
)
from backend.network.dataset import DEMO_STORY_PATH
from backend.network.seed_story import build_story, main
from backend.network.sources import FetchError, ReplayFetch
from backend.network.story import is_demo_story, story_sources, trace_demo_story

ITEM = "https://story.example/flood"
TAG_URL = "https://mastodon.social/api/v1/timelines/tag/floods?limit=40"
LEMMY_URL = f"https://lemmy.world/api/v3/search?q={quote(ITEM, safe='')}&type_=Url&listing_type=All&sort=New&limit=50"
HN_URL = (
    "https://hn.algolia.com/api/v1/search_by_date"
    f"?query={quote(ITEM, safe='')}&restrictSearchableAttributes=url&tags=story&hitsPerPage=50"
)
BLUESKY_UP = "bluesky is answering"
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def status(index, seconds=0):
    return {
        "uri": f"https://social.example/s/{index}",
        "url": f"https://social.example/@u{index}/{index}",
        "created_at": f"2026-03-01T09:{seconds // 60:02d}:{seconds % 60:02d}Z",
        "visibility": "public",
        "reblog": None,
        "content": "<p>Water levels rising</p>",
        "card": None,
        "tags": [{"name": "floods"}],
        "mentions": [],
        "account": {"id": str(index), "acct": f"u{index}@social.example"},
    }


def hit(index, seconds=600):
    return {
        "objectID": str(index),
        "author": f"writer{index}",
        "created_at": f"2026-03-01T10:{seconds // 60 % 60:02d}:00Z",
        "title": "A flood story",
        "url": ITEM,
    }


class ScriptedFetch:
    """Serve set responses that a test can change between polls."""

    def __init__(self):
        self.responses = {TAG_URL: [status(1)], LEMMY_URL: {"posts": []}, HN_URL: {"hits": [hit(1)]}, BLUESKY_UP: True}

    def __call__(self, url):
        if url in self.responses:
            return self.responses[url]
        if "/timelines/link" in url:
            raise FetchError("The platform refused the request (HTTP 404)", 404)
        if url.startswith("https://api.bsky.app/") and BLUESKY_UP in self.responses:
            return {"posts": []}
        raise FetchError("The platform refused the request (HTTP 403)", 403)


def monitor(fetch, **kwargs):
    return Monitor("watch-1", urls=(ITEM,), hashtags=("floods",), fetch=fetch, **kwargs)


# Monitoring


def test_a_watch_reads_two_or_more_real_platforms_and_says_which():
    snapshot = monitor(ScriptedFetch()).poll(NOW)
    assert snapshot["platforms_read"] == ["mastodon", "lemmy", "hackernews", "bluesky"]
    assert snapshot["new_posts"] == {"mastodon": 1, "lemmy": 0, "hackernews": 1, "bluesky": 0}
    assert snapshot["total_matching_posts"] == 2
    assert snapshot["polled_at"] == "2026-03-01T12:00:00Z"
    assert snapshot["synthetic"] is False
    assert {item["platform"] for item in snapshot["not_connected"]} >= {"reddit", "youtube"}


def test_a_platform_that_cannot_be_searched_is_not_counted_as_read():
    fetch = ScriptedFetch()
    snapshot = Monitor("watch-2", urls=(ITEM,), fetch=fetch).poll(NOW)
    assert "mastodon" not in snapshot["platforms_read"]
    assert snapshot["platforms_read"] == ["lemmy", "hackernews", "bluesky"]


def test_later_polls_report_only_new_posts_but_keep_everything():
    fetch = ScriptedFetch()
    watch = monitor(fetch)
    watch.poll(NOW)
    fetch.responses[HN_URL] = {"hits": [hit(1), hit(2)]}
    second = watch.poll(NOW)
    assert second["poll"] == 2
    assert second["new_posts"] == {"mastodon": 0, "lemmy": 0, "hackernews": 1, "bluesky": 0}
    assert second["total_matching_posts"] == 3
    third_row = next(item for item in second["platforms"] if item["platform"] == "hackernews")
    assert third_row["matching_posts"] == 2
    assert third_row["new_matching_posts"] == 1


def test_posts_that_disappear_from_search_are_kept():
    fetch = ScriptedFetch()
    watch = monitor(fetch)
    watch.poll(NOW)
    fetch.responses[HN_URL] = {"hits": []}
    assert watch.poll(NOW)["total_matching_posts"] == 2


def test_a_platform_going_down_raises_an_alert_and_keeps_earlier_posts():
    fetch = ScriptedFetch()
    watch = monitor(fetch)
    assert watch.poll(NOW)["alerts"] == []
    del fetch.responses[HN_URL]
    snapshot = watch.poll(NOW)
    assert snapshot["total_matching_posts"] == 2
    assert snapshot["platforms_read"] == ["mastodon", "lemmy", "bluesky"]
    alert = next(item for item in snapshot["alerts"] if item["type"] == "platform_unreachable")
    assert alert["platform"] == "hackernews"
    assert "HTTP 403" in alert["message"]


def test_results_are_available_through_the_getters():
    monitor(ScriptedFetch()).poll(NOW)
    payload = get_network_payload("watch-1")
    assert payload is not None
    assert len(payload["nodes"]) == 2
    module_result = get_network_module_result("watch-1")
    assert module_result is not None
    assert module_result["status"] == "complete"


def test_coordination_alert_is_a_signal_and_fires_once_per_group():
    fetch = ReplayFetch(DEMO_STORY_PATH)
    submission = get_demo_story()["submission"]
    watch = Monitor("watch-story", **submission, sources=story_sources(), fetch=fetch)
    first = watch.poll(NOW)
    alert = next(item for item in first["alerts"] if item["type"] == "coordination_signal")
    assert alert["accounts"] == 12
    assert "not proof" in alert["message"]
    assert not any(item["type"] == "coordination_signal" for item in watch.poll(NOW)["alerts"])


def test_a_watch_with_nothing_to_search_for_is_rejected():
    with pytest.raises(ValueError, match="needs text"):
        Monitor("empty", fetch=ScriptedFetch())


def test_state_survives_a_restart(tmp_path):
    path = tmp_path / "nested" / "state.json"
    fetch = ScriptedFetch()
    monitor(fetch, state_path=path).poll(NOW)
    restarted = monitor(fetch, state_path=path)
    assert restarted.polls == 1
    snapshot = restarted.poll(NOW)
    assert snapshot["poll"] == 2
    assert snapshot["new_posts"] == {"mastodon": 0, "lemmy": 0, "hackernews": 0, "bluesky": 0}
    assert snapshot["total_matching_posts"] == 2


def test_state_from_another_watch_is_refused(tmp_path):
    path = tmp_path / "state.json"
    monitor(ScriptedFetch(), state_path=path).poll(NOW)
    with pytest.raises(ValueError, match="different watch"):
        Monitor("other", urls=(ITEM,), fetch=ScriptedFetch(), state_path=path)


# The linked demo story


@pytest.fixture(scope="module")
def story():
    return trace_demo_story()


def flagged_cluster(story):
    return next(cluster for cluster in story.analysis.clusters if cluster["flagged"])


def test_story_fixture_matches_the_generator():
    assert json.loads(DEMO_STORY_PATH.read_text(encoding="utf-8")) == build_story()
    assert main(["--check"]) == 0


def test_story_is_labelled_synthetic_everywhere(story):
    document = json.loads(DEMO_STORY_PATH.read_text(encoding="utf-8"))
    assert document["synthetic"] is True
    assert "SYNTHETIC" in document["notice"]
    assert story.coverage["synthetic"] is True
    assert story.module_result["evidence"][0].startswith("SYNTHETIC DEMO DATA")
    assert "Replayed synthetic posts" in story.module_result["evidence"][1]
    assert all(node["synthetic"] is True for node in story.analysis.nodes)
    assert all(frame["synthetic"] is True for frame in story.analysis.timeline)
    assert get_demo_story()["synthetic"] is True


def test_story_uses_only_invented_names_and_addresses(story):
    assert {item["platform"] for item in story.coverage["platforms"]} == {"demo_microblog", "demo_forum", "demo_news"}
    assert all(item["label"].endswith("(synthetic)") for item in story.coverage["platforms"])
    assert all(node["handle"].startswith("synthetic_story_") or "synthetic_story_" in node["handle"] for node in story.analysis.nodes)
    assert all(item["permalink"] is None for item in story.coverage["spread"])
    document = DEMO_STORY_PATH.read_text(encoding="utf-8")
    assert "mastodon.social" not in document
    assert "lemmy.world" not in document


def test_story_finds_exactly_the_ring_across_three_platforms(story):
    cluster = flagged_cluster(story)
    assert cluster["size"] == 12
    assert all("ring" in member for member in cluster["members"])
    assert len(cluster["platforms"]) == 3
    assert any(edge["cross_platform"] for edge in story.analysis.edges if edge["type"] == "co_share")
    assert sum(item["flagged"] for item in story.analysis.clusters) == 1


def test_story_shows_the_earliest_post_found_is_not_the_source(story):
    origin = flagged_cluster(story)["earliest_observed"]
    assert "resident" in origin["account_id"]
    assert origin["in_cluster"] is False
    assert story.coverage["spread"][0]["earliest_found"] is True
    assert "resident" in story.coverage["spread"][0]["handle"]


def test_story_tags_the_target_and_leaves_late_repliers_unflagged(story):
    nodes = {node["id"]: node for node in story.analysis.nodes}
    targets = [node for node in nodes.values() if node["role"] == "target"]
    assert len(targets) == 1
    assert "mayor" in targets[0]["handle"]
    late = [node for node in nodes.values() if "late" in node["handle"]]
    assert len(late) == 3
    assert all(node["in_flagged_cluster"] is False for node in late)


def test_story_filters_out_search_results_that_do_not_match(story):
    handles = [node["handle"] for node in story.analysis.nodes]
    assert not any("decoy" in handle for handle in handles)
    assert any(item["results_returned"] > item["matching_posts"] for item in story.coverage["platforms"])


def test_story_is_served_through_the_getters_without_a_trace_call():
    payload = get_network_payload(DEMO_STORY_CASE_ID)
    assert payload is not None
    assert set(payload) == {"nodes", "edges", "timeline"}
    json.dumps(payload)
    assert get_network_clusters(DEMO_STORY_CASE_ID)
    coverage = get_network_coverage(DEMO_STORY_CASE_ID)
    assert coverage is not None
    assert coverage["mode"] == "replay"


def test_submitting_the_story_replays_it_offline(monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("The demo story must not use the network")

    monkeypatch.setattr("backend.network.sources.fetching.urllib.request.urlopen", no_network)
    result = trace_case("story-submission", **get_demo_story()["submission"])
    assert result["evidence"][0].startswith("SYNTHETIC DEMO DATA")
    assert result["score"] is not None
    assert trace_case("story-link-only", url=get_demo_story()["submission"]["url"])["score"] is not None


@pytest.mark.parametrize(
    ("text", "url", "expected"),
    [
        (None, "https://elmbrook-alerts.example/dam-failure", True),
        (None, "https://elmbrook-alerts.example/dam-failure/?utm_source=x", True),
        (None, "https://elmbrook-alerts.example/other", False),
        ("the elmbrook dam has failed", None, False),
        ("Some real post about a different flood somewhere", "https://news.example/flood", False),
        (None, None, False),
        ("", "", False),
    ],
)
def test_only_the_exact_story_sample_gets_the_story(text, url, expected):
    assert is_demo_story(text, url) is expected


def test_demo_story_case_cannot_be_overwritten():
    with pytest.raises(ValueError, match="reserved"):
        trace_case(DEMO_STORY_CASE_ID, url=ITEM, fetch=ScriptedFetch())
