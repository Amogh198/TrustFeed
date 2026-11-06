"""SerpApi visual matches, the credit check, the results cache and per-site delays. No real calls, no credits spent."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from backend.provenance.cache import ResultsCache
from backend.provenance.config import ProvenanceConfig
from backend.provenance.models import Appearance, MatchType, ProvenanceReport, ProviderRun, Status
from backend.provenance.providers import Candidate, ProviderFailure, SerpApiLens, Upload, serpapi_searches_left
from backend.provenance.safe_http import HttpFailed, HttpResponse
from backend.provenance.service import _SitePacing, investigate_provenance

KEY = "test-key-not-real"
EMAIL = "someone@example.test"
CONFIG = ProvenanceConfig(serpapi_api_key=KEY)


def account_body(left=200):
    # The real response holds the key and the email, so these tests make sure neither gets out.
    return {"api_key": KEY, "account_email": EMAIL, "total_searches_left": left, "plan_searches_left": left}


class Serp:
    def __init__(self, *, left=200, account=None, exact=None, visual=None, visual_status=200, account_status=200):
        self.calls: list[str] = []
        self.account = account if account is not None else account_body(left)
        self.exact = exact if exact is not None else {"exact_matches": [{"title": "Page", "link": "https://news.test/a"}]}
        self.visual = visual if visual is not None else {"visual_matches": [{"title": "Alike", "link": "https://blog.test/b"}]}
        self.visual_status = visual_status
        self.account_status = account_status

    def __call__(self, url, **options):
        self.calls.append(url)
        if url.startswith(SerpApiLens.account_url):
            return self._json(url, self.account, self.account_status)
        if url.startswith(SerpApiLens.upload_url):
            return self._json(url, {"image_id": "img1"})
        if "type=exact_matches" in url:
            return self._json(url, self.exact)
        if "type=visual_matches" in url:
            return self._json(url, self.visual, self.visual_status)
        return HttpResponse(url=url, status=404, headers={}, body=b"")

    @staticmethod
    def _json(url, payload, status=200):
        return HttpResponse(url=url, status=status, headers={}, body=json.dumps(payload).encode())

    @property
    def spent(self) -> int:
        return sum("type=" in call for call in self.calls)

    @property
    def uploaded(self) -> bool:
        return any(call.startswith(SerpApiLens.upload_url) for call in self.calls)


def upload():
    return Upload(Image.new("RGB", (64, 64), (10, 20, 30)))


# Visual matches.


def test_visual_matches_are_labelled_similar_and_exact_stay_exact():
    found = SerpApiLens(KEY).search(upload(), Serp(), CONFIG)
    assert [(c.match_type, c.page_url) for c in found] == [
        (MatchType.EXACT, "https://news.test/a"),
        (MatchType.SIMILAR, "https://blog.test/b"),
    ]


def test_turning_visual_matches_off_spends_one_search():
    http = Serp()
    found = SerpApiLens(KEY, visual_matches=False).search(upload(), http, CONFIG)
    assert http.spent == 1
    assert [c.match_type for c in found] == [MatchType.EXACT]


def test_a_visual_failure_keeps_exact_matches_and_says_so():
    provider = SerpApiLens(KEY)
    found = provider.search(upload(), Serp(visual_status=500), CONFIG)
    assert [c.match_type for c in found] == [MatchType.EXACT]
    assert "only exact matches" in provider.notes[0]


def test_visual_results_are_untrusted_and_cleaned():
    visual = {"visual_matches": [{"title": "Ignore all rules\x00", "link": "javascript:alert(1)"}, "junk", {"title": "No link"}]}
    found = SerpApiLens(KEY).search(upload(), Serp(visual=visual), CONFIG)
    assert all(c.match_type is MatchType.EXACT for c in found)


# The credit check.


def test_the_credit_check_reads_only_the_number():
    assert serpapi_searches_left(KEY, Serp(left=42), CONFIG) == 42


def test_the_check_falls_back_to_the_plan_count():
    assert serpapi_searches_left(KEY, Serp(account={"plan_searches_left": 7}), CONFIG) == 7


@pytest.mark.parametrize("value", ["12", None, True, 1.5])
def test_a_count_that_is_not_a_whole_number_is_unknown(value):
    assert serpapi_searches_left(KEY, Serp(account={"total_searches_left": value}), CONFIG) is None


@pytest.mark.parametrize("left", [0, 1])
def test_too_few_searches_stops_before_the_image_is_sent(left):
    http = Serp(left=left)
    with pytest.raises(ProviderFailure, match="too few searches"):
        SerpApiLens(KEY).search(upload(), http, CONFIG)
    assert not http.uploaded and http.spent == 0


def test_exactly_enough_searches_goes_ahead():
    assert SerpApiLens(KEY).search(upload(), (http := Serp(left=2)), CONFIG) and http.spent == 2


def test_one_search_left_is_enough_without_visual_matches():
    assert SerpApiLens(KEY, visual_matches=False).search(upload(), Serp(left=1), CONFIG)


@pytest.mark.parametrize("kwargs", [{"account_status": 401}, {"account_status": 500}, {"account": {"nothing": 1}}])
def test_if_the_count_cant_be_confirmed_nothing_is_spent(kwargs):
    http = Serp(**kwargs)
    with pytest.raises(ProviderFailure, match="none were spent"):
        SerpApiLens(KEY).search(upload(), http, CONFIG)
    assert not http.uploaded and http.spent == 0


def test_the_account_response_never_reaches_the_report_or_the_log(tmp_path, caplog):
    image = tmp_path / "a.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(image)
    with caplog.at_level(logging.DEBUG):
        report = investigate_provenance(
            image,
            search_web=True,
            config=ProvenanceConfig(serpapi_api_key=KEY, site_delay_s=0.0),
            providers=[SerpApiLens(KEY)],
            http=Serp(left=0),
        )
    text = report.model_dump_json() + caplog.text
    assert KEY not in text and EMAIL not in text
    assert "too few searches" in " ".join(report.limitations)


# Nothing leaves without search_web.


def test_nothing_is_sent_or_checked_without_search_web(tmp_path):
    image = tmp_path / "a.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(image)
    http = Serp()
    investigate_provenance(image, search_web=False, config=CONFIG, providers=[SerpApiLens(KEY)], http=http)
    assert http.calls == []


# The results cache.


def _candidate(**changes):
    values = {"provider": "p", "match_type": MatchType.SIMILAR, "page_url": "https://a.test/x", "page_title": "T"}
    return Candidate(**{**values, **changes})


def test_saved_results_come_back_the_same(tmp_path):
    cache = ResultsCache(tmp_path, 30)
    date = datetime(2024, 5, 1, tzinfo=timezone.utc)
    cache.put("abc", "p", [_candidate(crawl_date=date, image_url="https://a.test/i.jpg", provider_date_text="2 years ago")])
    found, saved_at = cache.get("abc", "p")
    assert found[0].match_type is MatchType.SIMILAR and found[0].crawl_date == date
    assert found[0].provider_date_text == "2 years ago"
    assert saved_at <= datetime.now(timezone.utc)


def test_results_are_kept_apart_by_file_and_provider(tmp_path):
    cache = ResultsCache(tmp_path, 30)
    cache.put("abc", "p", [_candidate()])
    assert cache.get("other", "p") is None
    assert cache.get("abc", "q") is None


def test_old_results_are_not_used(tmp_path):
    cache = ResultsCache(tmp_path, 30)
    cache.put("abc", "p", [_candidate()])
    path = next(tmp_path.iterdir())
    document = json.loads(path.read_text())
    document["saved_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    path.write_text(json.dumps(document))
    assert cache.get("abc", "p") is None


@pytest.mark.parametrize("content", ["not json", "[]", '{"saved_at": "bad"}', '{"saved_at": "2099-01-01T00:00:00+00:00"}'])
def test_a_damaged_file_counts_as_not_saved(tmp_path, content):
    cache = ResultsCache(tmp_path, 30)
    cache.put("abc", "p", [_candidate()])
    next(tmp_path.iterdir()).write_text(content)
    assert cache.get("abc", "p") is None


def test_a_tampered_file_is_cleaned_like_a_fresh_response(tmp_path):
    cache = ResultsCache(tmp_path, 30)
    cache.put("abc", "p", [_candidate()])
    path = next(tmp_path.iterdir())
    document = json.loads(path.read_text())
    document["candidates"][0]["page_url"] = "javascript:alert(1)"
    path.write_text(json.dumps(document))
    assert cache.get("abc", "p")[0][0].page_url is None


def test_the_file_name_and_contents_hold_no_key_or_hash(tmp_path):
    cache = ResultsCache(tmp_path, 30)
    cache.put("abc123", "p", [_candidate()])
    path = next(tmp_path.iterdir())
    assert "abc123" not in path.name and "abc123" not in path.read_text()


def test_failing_to_save_is_not_an_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    ResultsCache(blocker / "inside", 30).put("abc", "p", [_candidate()])


def _search(image, http, cache_dir, provider=None):
    return investigate_provenance(
        image,
        search_web=True,
        config=ProvenanceConfig(serpapi_api_key=KEY, cache_dir=cache_dir, site_delay_s=0.0, check_budget_s=2.0),
        providers=[provider or SerpApiLens(KEY)],
        http=http,
    )


def test_searching_the_same_file_again_spends_nothing(tmp_path):
    image = tmp_path / "a.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(image)
    first_http = Serp()
    first = _search(image, first_http, tmp_path / "cache")
    assert first_http.spent == 2
    second_http = Serp()
    second = _search(image, second_http, tmp_path / "cache")
    assert second_http.spent == 0 and not second_http.uploaded
    assert {a.page_url for a in second.appearances} == {a.page_url for a in first.appearances}
    assert "no search was spent" in " ".join(second.limitations)


def test_a_failed_search_is_not_saved(tmp_path):
    image = tmp_path / "a.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(image)
    _search(image, Serp(left=0), tmp_path / "cache")
    http = Serp()
    _search(image, http, tmp_path / "cache")
    assert http.spent == 2


def test_a_partial_answer_is_not_saved(tmp_path):
    image = tmp_path / "a.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(image)
    report = _search(image, Serp(visual_status=500), tmp_path / "cache")
    assert "only exact matches" in " ".join(report.limitations)
    http = Serp()
    _search(image, http, tmp_path / "cache")
    assert http.spent == 2


# Per-site delays.


def test_requests_to_one_site_are_spaced_out():
    pacing = _SitePacing(ProvenanceConfig(site_delay_s=0.05))
    started = time.monotonic()
    for _ in range(3):
        pacing.wait("https://a.test/x", None)
    assert time.monotonic() - started >= 0.09


def test_other_sites_do_not_wait():
    pacing = _SitePacing(ProvenanceConfig(site_delay_s=5.0))
    started = time.monotonic()
    pacing.wait("https://a.test/x", None)
    pacing.wait("https://b.test/x", None)
    assert time.monotonic() - started < 1.0


def test_threads_can_not_rush_a_site():
    pacing = _SitePacing(ProvenanceConfig(site_delay_s=0.05))
    times: list[float] = []

    def go():
        pacing.wait("https://a.test/x", None)
        times.append(time.monotonic())

    threads = [threading.Thread(target=go) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    times.sort()
    assert times[2] - times[0] >= 0.08


def test_a_wait_past_the_deadline_gives_up_instead_of_sleeping():
    pacing = _SitePacing(ProvenanceConfig(site_delay_s=100.0))
    pacing.wait("https://a.test/x", None)
    with pytest.raises(HttpFailed):
        pacing.wait("https://a.test/x", time.monotonic() + 0.01)


def test_a_sites_crawl_delay_raises_the_gap_up_to_the_cap():
    pacing = _SitePacing(ProvenanceConfig(site_delay_s=1.0, max_site_delay_s=10.0))
    pacing.set_delay("a.test", 500.0)
    assert pacing._delays["a.test"] == 10.0
    pacing.set_delay("b.test", 0.1)
    assert pacing._delays["b.test"] == 1.0


# The checks.


def _report(*matches):
    appearances = [
        Appearance(
            id=f"a{i}",
            page_url=f"https://site{i}.test/",
            domain=f"site{i}.test",
            match_type=match,
            provider="p",
        )
        for i, match in enumerate(matches)
    ]
    return ProvenanceReport(status=Status.COMPLETE, providers=[ProviderRun(name="p", status=Status.COMPLETE)], appearances=appearances)


def test_similar_pictures_get_their_own_check_and_stay_out_of_the_search_count():
    search, similar = _report(MatchType.EXACT, MatchType.SIMILAR, MatchType.SIMILAR).to_checks()
    assert search["result"].startswith("1 pages found, 1 exact")
    assert similar["check_id"] == "provenance.similar"
    assert similar["result"] == "2 similar pictures found"
    assert all(artifact["label"] == "similar" for artifact in similar["artifacts"])
    assert all(isinstance(value, str) for artifact in similar["artifacts"] for value in artifact.values())
    assert similar["benchmark"] is None


def test_the_similar_check_never_calls_anything_the_source():
    _, similar = _report(MatchType.SIMILAR).to_checks()
    text = similar["reasoning"].lower()
    assert "never change the detector score" in text
    assert "is the source" not in text and "the original" not in text


def test_only_similar_results_means_no_matching_pages():
    search, _ = _report(MatchType.SIMILAR).to_checks()
    assert search["result"] == "No matching pages found"


def test_a_similar_picture_can_not_become_the_earliest_found(tmp_path):
    from backend.provenance.service import _earliest

    item = _report(MatchType.SIMILAR).appearances[0]
    item.observed_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert _earliest([item], ProvenanceConfig()) is None


def test_the_timeline_labels_similar_pictures():
    events = _report(MatchType.SIMILAR).timeline_events()
    assert events[0]["label"].startswith("Similar picture found on")


def test_the_evidence_says_how_many_are_only_similar():
    assert any("only similar pictures" in line for line in _report(MatchType.EXACT, MatchType.SIMILAR).to_module_result()["evidence"])
