"""Tests for the comparison with chance, bursts, repeated media and the post-count baseline."""

from datetime import UTC, datetime, timedelta

from backend.network.analysis import analyze_network
from backend.network.config import CoordinationConfig
from backend.network.dataset import Account, Dataset, Post
from backend.network.significance import (
    ABOVE_CHANCE,
    NOT_ABOVE_CHANCE,
    NOTHING_OBSERVED,
    TEST_INCOMPLETE,
    find_bursts,
    link_fingerprints,
    permutation_test,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
CONFIG = CoordinationConfig(null_test_permutations=99)


def post(number, account, seconds, url=None, **extra):
    return Post(id=f"p{number}", account_id=account, created_at=START + timedelta(seconds=seconds), url=url, **extra)


def dataset(posts):
    accounts = tuple(Account(id=name, handle=name) for name in sorted({item.account_id for item in posts}))
    return Dataset(case_id="c", synthetic=True, accounts=accounts, posts=tuple(sorted(posts, key=lambda p: (p.created_at, p.id))))


def tight_group():
    """Six accounts post the same items seconds apart, hours from each other's other items."""
    posts = []
    for item in range(6):
        for member in range(6):
            posts.append(post(len(posts), f"a{member}", item * 7200 + member, f"https://x.example/{item}"))
    return posts


def one_moment():
    """Everyone posts both items in one short stretch, as after a news event."""
    posts = []
    for item in range(2):
        for member in range(8):
            posts.append(post(len(posts), f"a{member}", item * 3 + member, f"https://x.example/{item}"))
    return posts


def test_tight_repeated_timing_is_above_chance():
    result = permutation_test(tight_group(), CONFIG)
    assert result["verdict"] == ABOVE_CHANCE and 0 < result["p_value"] < 0.05
    assert result["observed"] > result["chance_mean"]


def test_everyone_posting_at_one_moment_is_not_above_chance():
    result = permutation_test(one_moment(), CONFIG)
    assert result["verdict"] == NOT_ABOVE_CHANCE


def test_nothing_found_flags_nothing_and_gives_no_score():
    analysis = analyze_network(dataset(one_moment()), CONFIG)
    assert analysis.tests["null_test"]["verdict"] == NOT_ABOVE_CHANCE
    assert not any(cluster["flagged"] for cluster in analysis.clusters)
    assert analysis.module_result["score"] is None
    assert analysis.tests["activity_baseline"] is None


def test_no_repeating_pairs_means_nothing_to_test():
    posts = [post(i, f"a{i}", i * 1000, f"https://x.example/{i}") for i in range(5)]
    assert permutation_test(posts, CONFIG)["verdict"] == NOTHING_OBSERVED


def test_running_out_of_time_gives_no_result():
    ticks = iter([0.0, 100.0])
    result = permutation_test(tight_group(), CONFIG, clock=lambda: next(ticks))
    assert result["verdict"] == TEST_INCOMPLETE and result["p_value"] is None


def test_same_seed_gives_the_same_result():
    assert permutation_test(tight_group(), CONFIG) == permutation_test(tight_group(), CONFIG)


def test_a_burst_is_found_only_against_a_quiet_background():
    quiet = [post(i, f"a{i % 3}", i * 60) for i in range(30)]
    loud = [post(100 + i, f"b{i}", 900 + i) for i in range(12)]
    result = find_bursts([*quiet, *loud], CONFIG)
    assert result["status"] == "complete" and result["bursts"][0]["posts"] >= 12
    assert find_bursts(quiet, CONFIG)["bursts"] == []


def test_too_short_a_span_has_no_usual_rate():
    assert find_bursts([post(i, f"a{i}", i) for i in range(20)], CONFIG)["status"] == "not_applicable"


def test_near_identical_fingerprints_become_one_image():
    posts = [
        post(1, "a", 0, media_fingerprint="ffffffffffffffff"),
        post(2, "b", 1, media_fingerprint="fffffffffffffff0"),
        post(3, "c", 2, media_fingerprint="0000000000000000"),
        post(4, "d", 3, media_fingerprint="not hex"),
    ]
    updated, groups = link_fingerprints(posts, 5)
    assert updated[0].media_hash == updated[1].media_hash and updated[0].media_hash
    assert updated[2].media_hash is None and updated[3].media_hash is None
    assert groups[0]["accounts"] == 2 and groups[0]["variants"] == 2


def test_one_account_reposting_its_own_image_is_not_repeated_media():
    posts = [post(1, "a", 0, media_fingerprint="ff"), post(2, "a", 1, media_fingerprint="ff")]
    assert link_fingerprints(posts, 5)[1] == []
