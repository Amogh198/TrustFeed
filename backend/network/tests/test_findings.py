"""Regression tests for the five findings recorded in AGENT_COORDINATION.md, section D."""

from itertools import pairwise

import pytest

from backend.network import (
    CoordinationConfig,
    analyze_network,
    load_dataset,
    parse_dataset,
)
from backend.network.coshare import (
    find_co_shares,
    normalize_text,
    normalize_url,
    post_signals,
)
from backend.network.dataset import Post, parse_timestamp

CONFIG = CoordinationConfig()


def members(prefix, count):
    return [f"{prefix}{index:02d}" for index in range(count)]


def node(analysis, account_id):
    return next(item for item in analysis.nodes if item["id"] == account_id)


def valid_raw():
    return {
        "metadata": {"case_id": "c"},
        "accounts": [{"id": "a", "handle": "h"}],
        "posts": [{"id": "p", "account_id": "a", "created_at": "2026-01-01T00:00:00Z"}],
    }


# Finding 1: accounts and edges must all be placeable on the time slider.


def test_every_edge_endpoint_appears_no_later_than_the_edge():
    analysis = analyze_network(load_dataset())
    appears = {item["id"]: item["appears_at"] for item in analysis.nodes}
    for edge in analysis.edges:
        for endpoint in (edge["source"], edge["target"]):
            assert appears[endpoint] is not None, edge["id"]
            assert appears[endpoint] <= edge["first_seen_at"], edge["id"]


def test_target_that_never_posted_appears_when_first_mentioned(make_dataset, ring_rows):
    analysis = analyze_network(parse_dataset(make_dataset(ring_rows(members("r", 6), mentions=("victim",)))))
    victim = node(analysis, "victim")
    assert victim["role"] == "target"
    assert victim["first_campaign_post_at"] is None
    first_mention = min(edge["first_seen_at"] for edge in analysis.edges if edge["target"] == "victim")
    assert victim["appears_at"] == first_mention


def test_account_with_no_spread_activity_never_appears(make_dataset, ring_rows):
    rows = [*ring_rows(members("r", 6)), ("quiet", 900000, "https://other.example/unrelated")]
    assert node(analyze_network(parse_dataset(make_dataset(rows))), "quiet")["appears_at"] is None


# Finding 2: a link only a few members shared doesn't define the campaign.


def test_side_link_shared_by_two_members_does_not_change_the_origin(make_dataset, ring_rows):
    side_link = "https://popular.example/news"
    side_rows = [(member, 50000 + index, side_link) for index, member in enumerate(members("r", 2))]
    rows = [("bystander", -5000, side_link), *ring_rows(members("r", 6)), *side_rows]
    analysis = analyze_network(parse_dataset(make_dataset(rows)))
    origin = analysis.clusters[0]["earliest_observed"]
    assert origin["account_id"] != "bystander"
    assert origin["in_cluster"] is True
    assert node(analysis, "bystander")["role"] == "background"
    assert node(analysis, "bystander")["first_campaign_post_at"] is None
    assert all("bystander" not in frame["new_account_ids"] for frame in analysis.timeline)


def test_earlier_outsider_still_counts_for_an_item_most_of_the_cluster_shared(make_dataset, ring_rows):
    rows = [("outsider", -5000, "https://site.example/item/0"), *ring_rows(members("r", 6))]
    origin = analyze_network(parse_dataset(make_dataset(rows))).clusters[0]["earliest_observed"]
    assert origin["account_id"] == "outsider"


def test_flagged_cluster_without_a_widely_shared_item_reports_no_origin(make_dataset):
    # A chain: each neighbouring pair shares its own two items, and none reaches three accounts.
    accounts = members("c", 6)
    rows = []
    for index, (left, right) in enumerate(pairwise(accounts)):
        for item in range(2):
            text = f"Identical copied message for pair {index} item {item}"
            url = f"https://x.example/{index}/{item}"
            hour = (index * 2 + item) * 3600
            rows += [(left, hour, url, f"hash{index}{item}", text), (right, hour + 2, url, f"hash{index}{item}", text)]
    config = CoordinationConfig(flag_score_threshold=0.1, louvain_resolution=0.01)
    analysis = analyze_network(parse_dataset(make_dataset(rows)), config)
    assert analysis.clusters[0]["flagged"] is True
    assert analysis.clusters[0]["earliest_observed"] is None
    assert analysis.timeline == []
    assert any("no single item" in line.lower() for line in analysis.module_result["limitations"])


def test_invalid_campaign_share_is_rejected():
    with pytest.raises(ValueError):
        CoordinationConfig(campaign_item_min_share=1.5)


# Finding 3: combining marks are letters' vowels in Indic scripts, not punctuation.


@pytest.mark.parametrize(
    ("first", "second"),
    [("पानी", "पीना"), ("कल", "काल"), ("தமிழ்", "தமிழ"), ("বাংলা", "বংলা")],
)
def test_different_words_stay_different(first, second):
    assert normalize_text(first) != normalize_text(second)


def test_indic_marks_survive_and_punctuation_still_goes():
    assert normalize_text("पानी, पीना!!") == "पानी पीना"


def test_zero_width_joiner_does_not_split_a_word():
    assert normalize_text("क्‍ष") == normalize_text("क्ष")


def test_disguised_hindi_copies_still_match():
    assert normalize_text("पानी असुरक्षित है!!! https://x.example/a") == normalize_text("...पानी असुरक्षित है")


# Finding 4: malformed input fails with a clear ValueError at parse time.


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["accounts"][0].pop("id"),
        lambda raw: raw["accounts"][0].pop("handle"),
        lambda raw: raw["accounts"][0].update(followers="many"),
        lambda raw: raw["accounts"][0].update(id=7),
        lambda raw: raw["accounts"].append("not a record"),
        lambda raw: raw.update(accounts="not a list"),
        lambda raw: raw["posts"][0].pop("id"),
        lambda raw: raw["posts"][0].pop("account_id"),
        lambda raw: raw["posts"][0].pop("created_at"),
        lambda raw: raw["posts"][0].update(created_at=1234),
        lambda raw: raw["posts"][0].update(created_at="yesterday"),
        lambda raw: raw["posts"][0].update(text=5),
        lambda raw: raw["posts"][0].update(url=5),
        lambda raw: raw["posts"][0].update(media_hash=5),
        lambda raw: raw["posts"][0].update(platform=5),
        lambda raw: raw["posts"][0].update(mentions=5),
        lambda raw: raw["posts"][0].update(mentions=[5]),
        lambda raw: raw["posts"].append(None),
        lambda raw: raw.update(posts=5),
        lambda raw: raw["metadata"].update(case_id=5),
    ],
)
def test_malformed_records_raise_value_error(mutate):
    raw = valid_raw()
    parse_dataset(raw)
    mutate(raw)
    with pytest.raises(ValueError):
        parse_dataset(raw)


@pytest.mark.parametrize("bad", ["http://[broken", "   ", "not a url"])
def test_unusable_url_has_no_signal_and_does_not_stop_analysis(make_dataset, bad):
    assert normalize_url(bad) is None
    post = Post(id="p", account_id="a", created_at=parse_timestamp("2026-01-01T00:00:00Z"), url=bad)
    assert list(post_signals(post, CONFIG)) == []
    raw = make_dataset([("a", 0, bad), ("b", 5, bad)])
    assert analyze_network(parse_dataset(raw)).edges == []


# Finding 5: items are counted across signals.


def co_share(make_dataset, rows):
    return find_co_shares(parse_dataset(make_dataset(rows)).posts, CONFIG)[("a", "b")]


TEXT_ONE = "A long enough identical message to count as text"


def test_two_items_matched_by_different_signals_count_as_two(make_dataset):
    pair = co_share(
        make_dataset,
        [
            ("a", 0, "https://x.example/1"),
            ("b", 10, "https://x.example/1"),
            ("a", 5000, None, None, TEXT_ONE),
            ("b", 5010, None, None, TEXT_ONE),
        ],
    )
    assert pair.signal_counts == {"url": 1, "media": 0, "text": 1}
    assert pair.distinct_items == 2


def test_three_signals_on_three_separate_items_count_as_three(make_dataset):
    pair = co_share(
        make_dataset,
        [
            ("a", 0, "https://x.example/1"),
            ("b", 10, "https://x.example/1"),
            ("a", 5000, None, None, TEXT_ONE),
            ("b", 5010, None, None, TEXT_ONE),
            ("a", 9000, None, "h1"),
            ("b", 9010, None, "h1"),
        ],
    )
    assert pair.distinct_items == 3


def test_one_post_carrying_two_matched_signals_links_them_as_one_item(make_dataset):
    # The same article: a's post has both link and text, and b posts each separately.
    pair = co_share(
        make_dataset,
        [
            ("a", 0, "https://x.example/1", None, TEXT_ONE),
            ("b", 10, "https://x.example/1"),
            ("b", 20, None, None, TEXT_ONE),
        ],
    )
    assert pair.distinct_items == 1


def test_shared_logo_does_not_merge_different_links(make_dataset):
    pair = co_share(
        make_dataset,
        [
            ("a", 0, "https://x.example/1", "logo"),
            ("b", 10, "https://x.example/1", "logo"),
            ("a", 5000, "https://x.example/2", "logo"),
            ("b", 5010, "https://x.example/2", "logo"),
        ],
    )
    assert pair.distinct_items == 2


def test_pair_with_two_different_signals_can_now_form_a_cluster_edge(make_dataset):
    rows = [
        ("a", 0, "https://x.example/1"),
        ("b", 10, "https://x.example/1"),
        ("a", 5000, None, None, TEXT_ONE),
        ("b", 5010, None, None, TEXT_ONE),
    ]
    edges = analyze_network(parse_dataset(make_dataset(rows))).edges
    assert [edge["type"] for edge in edges] == ["co_share"]
    assert edges[0]["weight"] == 2
