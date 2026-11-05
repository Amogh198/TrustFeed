import pytest

from backend.network.config import CoordinationConfig
from backend.network.coshare import find_co_shares, normalize_text, normalize_url
from backend.network.dataset import parse_dataset

CONFIG = CoordinationConfig()


def co_shares(raw):
    return find_co_shares(parse_dataset(raw).posts, CONFIG)


@pytest.mark.parametrize(
    ("delay", "expected"),
    [(0, True), (119, True), (120, True), (121, False)],
)
def test_window_boundary_is_inclusive_at_120_seconds(make_dataset, delay, expected):
    raw = make_dataset([("a", 0, "https://x.example/1"), ("b", delay, "https://x.example/1")])
    assert (("a", "b") in co_shares(raw)) is expected


def test_same_account_repeats_never_form_a_pair(make_dataset):
    raw = make_dataset([("a", 0, "https://x.example/1"), ("a", 5, "https://x.example/1")])
    assert co_shares(raw) == {}


def test_window_is_checked_between_posts_not_from_the_first_post(make_dataset):
    raw = make_dataset(
        [("a", 0, "https://x.example/1"), ("b", 100, "https://x.example/1"), ("c", 200, "https://x.example/1")]
    )
    assert set(co_shares(raw)) == {("a", "b"), ("b", "c")}


def test_one_post_matching_on_all_signals_counts_as_one_item_and_one_delay(make_dataset):
    text = "A long enough identical message to count as text"
    raw = make_dataset([("a", 0, "https://x.example/1", "h1", text), ("b", 30, "https://x.example/1", "h1", text)])
    pair = co_shares(raw)[("a", "b")]
    assert pair.distinct_items == 1
    assert pair.signal_counts == {"url": 1, "media": 1, "text": 1}
    assert list(pair.delays.values()) == [30]


def test_distinct_items_are_counted_across_items(make_dataset):
    raw = make_dataset(
        [
            ("a", 0, "https://x.example/1"),
            ("b", 10, "https://x.example/1"),
            ("a", 5000, "https://x.example/2"),
            ("b", 5010, "https://x.example/2"),
        ]
    )
    assert co_shares(raw)[("a", "b")].distinct_items == 2


def test_short_text_is_not_a_signal(make_dataset):
    raw = make_dataset([("a", 0, None, None, "Breaking news!"), ("b", 5, None, None, "breaking news")])
    assert co_shares(raw) == {}


def test_disguised_copies_match_after_normalization():
    original = "Share this: the Water is UNSAFE, officials are hiding it"
    copy = "...share this the water is unsafe - officials are hiding it!! https://x.example/a"
    assert normalize_text(original) == normalize_text(copy)


def test_tracking_parameters_and_fragments_do_not_change_a_url():
    assert normalize_url("HTTPS://Site.Example/a/?utm_source=x&b=1#top") == normalize_url("https://site.example/a?b=1")


def test_different_query_values_stay_different_urls():
    assert normalize_url("https://site.example/a?id=1") != normalize_url("https://site.example/a?id=2")
