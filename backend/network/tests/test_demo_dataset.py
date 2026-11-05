"""Checks on the committed demo data and the interface the API lane consumes."""

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from backend.network import (
    DEMO_CASE_ID,
    analyze_network,
    get_network_clusters,
    get_network_module_result,
    get_network_payload,
    load_dataset,
)
from backend.network.dataset import DEMO_DATASET_PATH, parse_timestamp
from backend.network.seed_network import GROUND_TRUTH_PATH, build_demo_dataset, render

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_FILES = ("analysis", "clusters", "config", "coshare", "dataset", "roles", "service", "timeline")


def demo_payload():
    payload = get_network_payload(DEMO_CASE_ID)
    assert payload is not None
    return payload


def demo_result():
    result = get_network_module_result(DEMO_CASE_ID)
    assert result is not None
    return result


@pytest.fixture(scope="module")
def truth():
    return json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def raw():
    return json.loads(DEMO_DATASET_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def analysis():
    return analyze_network(load_dataset())


def test_generator_meets_size_requirements(raw, truth):
    assert len(raw["accounts"]) >= 300
    assert len(truth["coordinated_accounts"]) >= 30


def test_committed_fixtures_match_the_generator(raw, truth):
    dataset, ground_truth = build_demo_dataset()
    assert raw == dataset
    assert truth == ground_truth


def test_generator_output_is_byte_identical_across_hash_seeds():
    code = (
        "import hashlib; from backend.network.seed_network import build_demo_dataset, render;"
        "d, g = build_demo_dataset(); print(hashlib.sha256((render(d) + render(g)).encode()).hexdigest())"
    )
    digests = {
        subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for seed in ("1", "2", "12345")
    }
    assert len(digests) == 1


def test_a_different_seed_changes_the_data():
    assert render(build_demo_dataset(1)[0]) != render(build_demo_dataset(2)[0])


def test_every_record_and_file_is_labelled_synthetic(raw, truth):
    assert raw["metadata"]["synthetic"] is True
    assert truth["synthetic"] is True
    assert "SYNTHETIC" in raw["metadata"]["notice"]
    assert all(account["synthetic"] is True for account in raw["accounts"])
    assert all(post["synthetic"] is True for post in raw["posts"])


def test_data_uses_only_reserved_domains_and_synthetic_handles(raw):
    assert all(account["handle"].startswith("synthetic_user_") for account in raw["accounts"])
    urls = [post["url"] for post in raw["posts"] if post["url"]]
    assert urls
    assert all(".example/" in url for url in urls)


def test_demo_covers_several_invented_platforms(raw, analysis):
    assert {post["platform"] for post in raw["posts"]} == {"demo_forum", "demo_microblog", "demo_video"}
    flagged = next(cluster for cluster in analysis.clusters if cluster["flagged"])
    assert len(flagged["platforms"]) == 3
    assert any(edge["cross_platform"] for edge in analysis.edges if edge["type"] == "co_share")


def test_engine_never_reads_ground_truth():
    for name in ENGINE_FILES:
        source = (REPO_ROOT / "backend" / "network" / f"{name}.py").read_text(encoding="utf-8")
        assert "ground_truth" not in source


def test_planted_cluster_is_recovered_as_one_cluster(analysis, truth):
    flagged = [cluster for cluster in analysis.clusters if cluster["flagged"]]
    assert len(flagged) == 1
    assert set(flagged[0]["members"]) == set(truth["coordinated_accounts"])


def test_seed_account_is_the_earliest_observed(analysis, truth):
    flagged = next(cluster for cluster in analysis.clusters if cluster["flagged"])
    origin = flagged["earliest_observed"]
    assert origin["account_id"] == truth["seed_account"]
    assert origin["in_cluster"] is True
    assert origin["ambiguous"] is False


def test_targets_are_tagged(analysis, truth):
    tagged = {node["id"] for node in analysis.nodes if node["role"] == "target"}
    assert tagged == set(truth["target_accounts"])


@pytest.mark.parametrize("group", ["organic_burst", "late_resharers", "syndication_group"])
def test_hard_negatives_are_not_flagged(analysis, truth, group):
    nodes = {node["id"]: node for node in analysis.nodes}
    for account in truth["hard_negatives"][group]:
        assert nodes[account]["in_flagged_cluster"] is False
        assert nodes[account]["role"] == "background"


def test_peripheral_accounts_are_less_connected_than_the_core(analysis, truth):
    nodes = {node["id"]: node for node in analysis.nodes}
    peripheral = truth["peripheral_accounts"]
    core = set(truth["coordinated_accounts"]) - set(peripheral)
    assert max(nodes[item]["weighted_degree"] for item in peripheral) < min(nodes[item]["weighted_degree"] for item in core)


def test_co_share_edges_respect_the_window(analysis):
    delays = [edge["min_delay_seconds"] for edge in analysis.edges if edge["type"] != "mention"]
    assert delays
    assert max(delays) <= 120
    assert all(edge["median_delay_seconds"] <= 120 for edge in analysis.edges if edge["type"] != "mention")


def test_one_role_per_origin_and_expected_role_counts(analysis, truth):
    counts = Counter(node["role"] for node in analysis.nodes)
    assert counts["origin_candidate"] == 1
    assert counts["target"] == len(truth["target_accounts"])


def test_payload_contract(analysis):
    payload = demo_payload()
    assert set(payload) == {"nodes", "edges", "timeline"}
    for key in payload:
        assert isinstance(payload[key], list)
        assert all(isinstance(item, dict) for item in payload[key])
    json.dumps(payload)
    node_ids = {node["id"] for node in payload["nodes"]}
    assert all(edge["source"] in node_ids and edge["target"] in node_ids for edge in payload["edges"])
    assert len({edge["id"] for edge in payload["edges"]}) == len(payload["edges"])
    assert all(node["synthetic"] is True for node in payload["nodes"])
    assert all(frame["synthetic"] is True for frame in payload["timeline"])


def test_timestamps_are_utc_iso8601(analysis):
    for edge in analysis.edges:
        assert edge["first_seen_at"].endswith("Z")
        parse_timestamp(edge["first_seen_at"])


def test_module_result_contract():
    result = demo_result()
    assert set(result) == {"status", "score", "confidence", "evidence", "limitations"}
    assert result["status"] == "complete"
    assert 0 <= result["score"] <= 1
    assert result["confidence"] is None
    assert result["evidence"][0].startswith("SYNTHETIC DEMO DATA")
    assert result["limitations"]
    assert all(isinstance(line, str) for line in result["evidence"] + result["limitations"])


def test_module_result_distinguishes_spread_from_authenticity_and_avoids_attribution():
    result = demo_result()
    limitations = " ".join(result["limitations"])
    assert "not whether the content is authentic" in limitations
    assert "does not establish intent" in limitations
    assert "bot" not in " ".join(result["evidence"]).lower()


def test_unknown_cases_never_receive_demo_data():
    assert get_network_payload("any-user-case") is None
    assert get_network_module_result("any-user-case") is None
    assert get_network_clusters("any-user-case") is None


def test_callers_cannot_corrupt_the_cached_result():
    payload = demo_payload()
    payload["nodes"].clear()
    assert demo_payload()["nodes"]


def test_seed_check_cli_passes_on_committed_fixtures():
    completed = subprocess.run(
        [sys.executable, "-m", "backend.network.seed_network", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
