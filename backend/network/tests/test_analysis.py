import json

import pytest

from backend.network import CoordinationConfig, analyze_network, parse_dataset


def analyze(raw, config=None):
    return analyze_network(parse_dataset(raw), config)


def node(analysis, account_id):
    return next(item for item in analysis.nodes if item["id"] == account_id)


def members(prefix, count):
    return [f"{prefix}{index:02d}" for index in range(count)]


def test_ring_is_flagged_with_explainable_score(make_dataset, ring_rows):
    analysis = analyze(make_dataset(ring_rows(members("r", 8))))
    assert len(analysis.clusters) == 1
    cluster = analysis.clusters[0]
    assert cluster["flagged"] is True
    assert cluster["size"] == 8
    assert 0 <= cluster["coordination_risk_score"] <= 1
    weighted = sum(cluster["score_weights"][name] * value for name, value in cluster["score_components"].items())
    assert cluster["coordination_risk_score"] == pytest.approx(weighted, abs=0.001)


def test_single_shared_item_is_not_coordination(make_dataset, ring_rows):
    analysis = analyze(make_dataset(ring_rows(members("r", 20), items=1)))
    assert analysis.clusters == []
    assert {edge["type"] for edge in analysis.edges} == {"weak_co_share"}
    assert analysis.module_result["score"] is None
    assert analysis.module_result["status"] == "complete"
    assert analysis.module_result["limitations"][0].startswith("Inconclusive")


def test_small_group_is_inconclusive_not_flagged(make_dataset, ring_rows):
    analysis = analyze(make_dataset(ring_rows(members("r", 3))))
    cluster = analysis.clusters[0]
    assert cluster["flagged"] is False
    assert cluster["risk_level"] == "inconclusive"
    assert analysis.module_result["score"] is None
    assert {node(analysis, member)["role"] for member in cluster["members"]} == {"background"}
    assert analysis.timeline == []


def test_low_score_large_group_is_not_flagged(make_dataset):
    # A pair sharing two links, slow within the window and with no text or media.
    rows = []
    for item in range(2):
        for index, account in enumerate(members("r", 2)):
            rows.append((account, item * 3600 + index * 110, f"https://x.example/{item}"))
    strict = CoordinationConfig(min_cluster_size=2, flag_score_threshold=0.5)
    analysis = analyze(make_dataset(rows), strict)
    assert analysis.clusters[0]["coordination_risk_score"] < 0.5
    assert analysis.clusters[0]["flagged"] is False


def test_two_separate_campaigns_stay_separate_even_with_bridges(make_dataset, ring_rows):
    first = members("a", 12)
    second = members("b", 12)
    rows = ring_rows(first, prefix="first") + ring_rows(second, prefix="second", start=100000)
    # Two pairs also co-share two unrelated items, which joins the campaigns in the graph.
    for item, (left, right) in enumerate([(first[0], second[0]), (first[1], second[1])]):
        for repeat in range(2):
            url = f"https://bridge.example/{item}/{repeat}"
            rows += [(left, 300000 + item * 5000 + repeat * 1000, url), (right, 300010 + item * 5000 + repeat * 1000, url)]
    analysis = analyze(make_dataset(rows))
    flagged = sorted(cluster["size"] for cluster in analysis.clusters if cluster["flagged"])
    assert flagged == [12, 12]


def test_origin_is_the_earliest_post_and_can_be_outside_the_cluster(make_dataset, ring_rows):
    rows = ring_rows(members("r", 6), start=1000)
    rows.append(("outsider", 0, "https://site.example/item/0"))
    analysis = analyze(make_dataset(rows))
    origin = analysis.clusters[0]["earliest_observed"]
    assert origin["account_id"] == "outsider"
    assert origin["in_cluster"] is False
    assert node(analysis, "outsider")["role"] == "origin_candidate"
    assert any("outside the cluster" in line for line in analysis.module_result["evidence"])


def test_near_simultaneous_first_posts_mark_the_origin_ambiguous(make_dataset, ring_rows):
    # Members post two seconds apart, inside the five-second tie window.
    analysis = analyze(make_dataset(ring_rows(members("r", 6))))
    origin = analysis.clusters[0]["earliest_observed"]
    assert origin["ambiguous"] is True
    assert any("uncertain" in line for line in analysis.module_result["evidence"])


def test_targets_need_mentions_from_several_members(make_dataset, ring_rows):
    rows = ring_rows(members("r", 6), mentions=("victim",))
    rows.append(("r00", 50000, None, None, "An unrelated post mentioning somebody once", ("rarely",)))
    analysis = analyze(make_dataset(rows))
    assert node(analysis, "victim")["role"] == "target"
    assert node(analysis, "rarely")["role"] == "background"


def test_late_reshares_are_not_cluster_members_but_appear_in_timeline(make_dataset, ring_rows):
    rows = ring_rows(members("r", 6))
    rows.append(("late", 90000, "https://site.example/item/0"))
    analysis = analyze(make_dataset(rows))
    assert "late" not in analysis.clusters[0]["members"]
    assert node(analysis, "late")["in_flagged_cluster"] is False
    assert node(analysis, "late")["first_campaign_post_at"] is not None
    assert "late" in analysis.timeline[-1]["new_account_ids"]


def test_timeline_is_ordered_and_cumulative(make_dataset, ring_rows):
    analysis = analyze(make_dataset(ring_rows(members("r", 8))))
    offsets = [frame["offset_seconds"] for frame in analysis.timeline]
    assert offsets == sorted(offsets)
    assert offsets[0] == 0
    assert analysis.timeline[-1]["cumulative_account_count"] == 8
    assert sum(len(frame["new_account_ids"]) for frame in analysis.timeline) == 8


def test_returning_accounts_are_not_counted_as_new_again(make_dataset, ring_rows):
    rows = ring_rows(members("r", 6))
    rows.append(("late", 90000, "https://site.example/item/0"))
    rows.append(("r00", 200000, "https://site.example/item/0"))
    analysis = analyze(make_dataset(rows))
    last = analysis.timeline[-1]
    assert last["new_account_ids"] == []
    assert last["cumulative_account_count"] == 7
    assert last["cumulative_cluster_member_count"] == 6


def test_empty_dataset_reports_not_applicable_without_a_score(make_dataset):
    analysis = analyze(make_dataset([], extra_accounts=["a"]))
    assert analysis.module_result["status"] == "not_applicable"
    assert analysis.module_result["score"] is None
    assert analysis.payload()["edges"] == []
    assert analysis.payload()["timeline"] == []


def test_real_data_is_not_labelled_synthetic(make_dataset, ring_rows):
    analysis = analyze(make_dataset(ring_rows(members("r", 6)), synthetic=False))
    assert not any("SYNTHETIC" in line for line in analysis.module_result["evidence"])
    assert node(analysis, "r00")["synthetic"] is False


def test_input_order_does_not_change_the_result(make_dataset, ring_rows):
    raw = make_dataset(ring_rows(members("r", 10)))
    baseline = analyze(raw)
    raw["posts"].reverse()
    raw["accounts"].reverse()
    shuffled = analyze(raw)
    assert json.dumps(baseline.payload(), sort_keys=True) == json.dumps(shuffled.payload(), sort_keys=True)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["posts"][0].update(account_id="ghost"),
        lambda raw: raw["posts"][0].update(mentions=["ghost"]),
        lambda raw: raw["posts"][0].update(created_at="2026-01-01T12:00:00"),
        lambda raw: raw["posts"][1].update(id=raw["posts"][0]["id"]),
        lambda raw: raw["accounts"].append(dict(raw["accounts"][0])),
        lambda raw: raw["metadata"].pop("case_id"),
    ],
    ids=["unknown-author", "unknown-mention", "naive-timestamp", "duplicate-post", "duplicate-account", "no-case-id"],
)
def test_invalid_datasets_are_rejected(make_dataset, mutate):
    raw = make_dataset([("a", 0, "https://x.example/1"), ("b", 5, "https://x.example/1")])
    mutate(raw)
    with pytest.raises(ValueError):
        parse_dataset(raw)


@pytest.mark.parametrize("kwargs", [{"window_seconds": 0}, {"min_shared_items": 0}, {"timeline_bucket_seconds": 0}])
def test_invalid_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        CoordinationConfig(**kwargs)
