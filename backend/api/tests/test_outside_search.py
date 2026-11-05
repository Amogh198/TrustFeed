"""The opt-in source search and public-post trace. These tests never touch the network."""

import logging
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.app import main
from backend.api.app.main import MEDIA_UPLOAD_PATH, app
from backend.api.app.store import CaseStore
from backend.api.tests.test_wiring import SCAM_TEXT, png_bytes
from backend.media import analyze_media
from backend.media.tests.helpers import FakeClassifier
from backend.network.story import get_demo_story
from backend.provenance import MatchType, ProvenanceReport, Status
from backend.provenance.models import Appearance, DateSource

client = TestClient(app)
EMPTY_NETWORK = {"nodes": [], "edges": [], "timeline": []}
MEDIA_FIELDS = {"file": ("a.png", png_bytes())}


def appearance(number: int, match_type=MatchType.EXACT, observed_at=None) -> Appearance:
    return Appearance(
        id=f"a{number}",
        page_url=f"https://news.example/{number}",
        domain="news.example",
        match_type=match_type,
        observed_at=observed_at,
        date_source=DateSource.PAGE_METADATA if observed_at else DateSource.NONE,
        provider="fake",
    )


def report(*appearances: Appearance, **fields) -> ProvenanceReport:
    return ProvenanceReport(status=Status.COMPLETE, appearances=list(appearances), limitations=["A limit."], **fields)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail a test that reaches outside, even if the code under test swallows the error.

    Loopback stays allowed because asyncio uses it for its own event loop on Windows.
    """
    attempts = []
    real_connect = socket.socket.connect

    def lookup(host, *args, **kwargs):
        attempts.append(host)
        raise OSError("Blocked by the test's network guard")

    def connect(self, address):
        if address[0] in ("127.0.0.1", "::1"):
            return real_connect(self, address)
        attempts.append(address[0])
        raise OSError("Blocked by the test's network guard")

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    monkeypatch.setattr(socket.socket, "connect", connect)
    yield
    assert attempts == [], "A test tried to reach the network"


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    monkeypatch.setattr(main, "analyze_media", lambda path: analyze_media(path, classifier=FakeClassifier(0.1)))


@pytest.fixture
def outside(monkeypatch):
    """Record every call to the two functions that can send data out."""
    calls: dict[str, list] = {"search": [], "trace": []}
    results: dict[str, Callable] = {
        "search": lambda: report(),
        "trace": lambda: {"status": "complete", "score": None, "confidence": None, "evidence": ["Traced."]},
    }
    real_investigate = main.investigate_provenance

    def investigate(path, *, search_web):
        assert Path(path).exists(), "The file has to exist while it is searched"
        if not search_web:
            return real_investigate(path, search_web=False)
        calls["search"].append(Path(path))
        return results["search"]()

    def trace(case_id, *, text=None, url=None, urls=()):
        calls["trace"].append({"case_id": case_id, "text": text, "url": url, "urls": urls})
        return results["trace"]()

    real_link = main.investigate_link

    def check_link(url, *, offline_reason=None):
        # Consent reaches this function as "no offline reason". The check itself stays offline here.
        if offline_reason is None:
            calls.setdefault("link", []).append(url)
        return real_link(url, offline_reason=offline_reason or "Recorded test.")

    monkeypatch.setattr(main, "investigate_link", check_link)
    monkeypatch.setattr(main, "investigate_provenance", investigate)
    monkeypatch.setattr(main, "trace_case", trace)
    return calls, results


# Nothing leaves the server by default


def test_upload_sends_nothing_by_default(outside):
    calls, _ = outside
    body = client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"text": SCAM_TEXT}).json()
    assert calls == {"search": [], "trace": []}
    assert body["modules"]["provenance"]["status"] == "not_applicable"
    assert "not sent" in " ".join(body["modules"]["provenance"]["limitations"])
    assert body["modules"]["network"]["status"] == "unavailable"
    assert "nothing was sent" in " ".join(body["modules"]["network"]["limitations"])


def test_json_case_sends_nothing_by_default(outside):
    calls, _ = outside
    body = client.post("/api/cases/analyze", json={"text": SCAM_TEXT, "url": "https://example.org/a"}).json()
    assert calls == {"search": [], "trace": []}
    assert body["modules"]["provenance"]["status"] == "not_applicable"
    assert body["modules"]["network"]["status"] == "unavailable"


def test_false_is_not_read_as_true(outside):
    calls, _ = outside
    client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "false"})
    client.post("/api/cases/analyze", json={"text": SCAM_TEXT, "search_web": False})
    assert calls == {"search": [], "trace": []}


def test_invalid_opt_in_is_rejected_and_sends_nothing(outside):
    calls, _ = outside
    assert client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "maybe"}).status_code == 422
    assert calls == {"search": [], "trace": []}


def test_replay_scenario_sends_nothing(outside):
    calls, _ = outside
    scenario = client.get("/api/replay/scenarios").json()["scenarios"][0]["id"]
    body = client.post(f"/api/replay/{scenario}/start").json()
    assert calls == {"search": [], "trace": []}
    assert body["modules"]["provenance"]["status"] == "not_applicable"


@pytest.mark.parametrize("content", [b"", b"plain text, not media", b"\x89PNG\r\n\x1a\nbroken"])
def test_rejected_file_is_never_searched_even_with_opt_in(outside, content):
    calls, _ = outside
    response = client.post(MEDIA_UPLOAD_PATH, files={"file": ("a.png", content)}, data={"search_web": "true"})
    assert response.status_code in (415, 422)
    assert calls == {"search": [], "trace": []}


# With the opt-in


def test_opt_in_searches_while_the_file_exists_then_deletes_it(outside):
    calls, _ = outside
    response = client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "true"})
    assert response.status_code == 200
    assert len(calls["search"]) == 1
    assert not calls["search"][0].exists()


def test_page_links_and_text_reach_the_trace_under_the_case_id(outside):
    calls, results = outside
    results["search"] = lambda: report(appearance(1), appearance(2, MatchType.PARTIAL))
    body = client.post(
        MEDIA_UPLOAD_PATH,
        files=MEDIA_FIELDS,
        data={"search_web": "true", "text": SCAM_TEXT, "url": "https://example.org/a"},
    ).json()
    assert calls["trace"] == [
        {
            "case_id": body["case_id"],
            "text": SCAM_TEXT,
            "url": "https://example.org/a",
            "urls": ("https://news.example/1", "https://news.example/2"),
        }
    ]
    assert body["modules"]["network"]["evidence"] == ["Traced."]
    assert "2 pages" in " ".join(body["modules"]["network"]["limitations"])


def test_merely_similar_pictures_are_not_traced(outside):
    calls, results = outside
    results["search"] = lambda: report(appearance(1, MatchType.SIMILAR), appearance(2))
    client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "true"})
    assert calls["trace"][0]["urls"] == ("https://news.example/2",)


def test_traced_links_are_capped(outside):
    calls, results = outside
    results["search"] = lambda: report(*(appearance(number) for number in range(1, 30)))
    client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "true"})
    assert len(calls["trace"][0]["urls"]) == main.MAX_TRACED_PAGE_LINKS


def test_blank_text_is_not_sent_to_the_trace(outside):
    calls, _ = outside
    client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "true", "text": "   "})
    assert calls["trace"][0]["text"] is None


def test_json_case_can_opt_in_to_the_trace(outside):
    calls, _ = outside
    body = client.post("/api/cases/analyze", json={"text": SCAM_TEXT, "search_web": True}).json()
    assert calls["search"] == []
    assert calls["trace"][0]["case_id"] == body["case_id"]
    assert calls["trace"][0]["urls"] == ()
    assert body["modules"]["network"]["status"] == "complete"
    assert body["modules"]["provenance"]["status"] == "not_applicable"


# Search and trace results never change the risk


def test_results_do_not_change_the_risk_or_invent_a_score(outside):
    _, results = outside
    baseline = client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS).json()
    results["search"] = lambda: report(appearance(1, observed_at=datetime(2020, 1, 1, tzinfo=UTC)))
    results["trace"] = lambda: {"status": "complete", "score": 0.99, "confidence": None}
    body = client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "true"}).json()
    assert body["overall_risk"] == baseline["overall_risk"]
    assert body["modules"]["provenance"]["score"] is None
    assert body["modules"]["provenance"]["confidence"] is None
    assert any("do not change the overall risk" in line for line in body["uncertainties"])


# Failures are contained


def test_failed_trace_is_reported_without_its_content(outside, caplog):
    _, results = outside

    def crash():
        raise RuntimeError(f"failed while reading {SCAM_TEXT}")

    results["trace"] = crash
    with caplog.at_level(logging.DEBUG):
        response = client.post(
            MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "true", "text": SCAM_TEXT}
        )
    assert response.status_code == 200
    network = response.json()["modules"]["network"]
    assert network["status"] == "unavailable"
    assert network["score"] is None
    assert "failed unexpectedly" in network["limitations"][0]
    assert "Urgent" not in " ".join(network["limitations"])
    assert "Urgent" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert client.get(f"/api/network/{response.json()['case_id']}").json() == EMPTY_NETWORK


def test_unavailable_search_still_returns_the_media_result(outside):
    _, results = outside
    results["search"] = lambda: ProvenanceReport(status=Status.UNAVAILABLE, limitations=["No key is set."])
    body = client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "true"}).json()
    assert body["modules"]["media"]["status"] == "complete"
    assert body["modules"]["provenance"] == {
        "status": "unavailable",
        "score": None,
        "confidence": None,
        "evidence": [],
        "limitations": ["No key is set."],
    }


def test_opt_in_with_no_keys_says_no_search_ran(monkeypatch):
    for name in ("GOOGLE_VISION_API_KEY", "TINEYE_API_KEY", "SERPAPI_API_KEY", "PROVENANCE_REPLAY_PATH"):
        monkeypatch.delenv(name, raising=False)
    # With no text and no key there is nothing to send, so the guard above would catch any call.
    body = client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "true"}).json()
    assert body["modules"]["provenance"]["status"] == "unavailable"
    assert "no web search was run" in " ".join(body["modules"]["provenance"]["limitations"])
    assert body["modules"]["network"]["status"] == "unavailable"
    assert "Nothing to search for" in body["modules"]["network"]["limitations"][0]


# Offline demos


def test_replay_mode_never_goes_live(outside):
    calls, results = outside
    results["search"] = lambda: report(appearance(1), replay=True)
    body = client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "true", "text": SCAM_TEXT}).json()
    assert calls["trace"] == []
    assert "stays offline" in body["modules"]["network"]["limitations"][0]
    assert any("replayed from a recording" in line for line in body["uncertainties"])


def test_demo_story_still_replays_in_replay_mode(outside):
    calls, results = outside
    results["search"] = lambda: report(replay=True)
    submission = get_demo_story()["submission"]
    client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={**submission, "search_web": "true"})
    assert len(calls["trace"]) == 1


def test_demo_story_replays_offline_and_is_labelled_synthetic():
    # The autouse guard fails this test if anything tries to connect.
    submission = get_demo_story()["submission"]
    body = client.post("/api/cases/analyze", json={**submission, "search_web": True}).json()
    case_id = body["case_id"]
    assert "SYNTHETIC" in " ".join(body["modules"]["network"]["evidence"])
    assert any("labelled synthetic replay" in line for line in body["uncertainties"])
    nodes = client.get(f"/api/network/{case_id}").json()["nodes"]
    assert nodes and all(node["synthetic"] for node in nodes)
    coverage = client.get(f"/api/network/{case_id}/coverage").json()
    assert coverage["synthetic"] is True
    assert all(post["permalink"] is None for post in coverage["spread"])
    events = client.get(f"/api/cases/{case_id}/timeline").json()["events"]
    assert events and all(event["synthetic"] for event in events)


# Provenance route


def test_demo_case_has_labelled_provenance():
    module = client.get("/api/cases/demo-001").json()["modules"]["provenance"]
    assert module["status"] == "complete"
    assert module["score"] is None
    assert module["evidence"][0].startswith("SYNTHETIC")
    full = client.get("/api/cases/demo-001/provenance").json()
    assert full["case_id"] == "demo-001"
    assert full["synthetic"] is True and full["replay"] is True
    assert full["appearances"]
    assert full["earliest_found"]["caveat"].startswith("Earliest appearance these searches found")


def test_saved_report_is_returned_under_the_case_id(outside):
    _, results = outside
    results["search"] = lambda: report(appearance(1))
    case_id = client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "true"}).json()["case_id"]
    full = client.get(f"/api/cases/{case_id}/provenance").json()
    assert full["case_id"] == case_id
    assert [item["page_url"] for item in full["appearances"]] == ["https://news.example/1"]


def test_case_without_a_search_has_a_plain_answer():
    case_id = client.post("/api/cases/analyze", json={"text": SCAM_TEXT}).json()["case_id"]
    full = client.get(f"/api/cases/{case_id}/provenance").json()
    assert full["status"] == "not_applicable"
    assert full["appearances"] == []
    assert full["earliest_found"] is None
    assert client.get(f"/api/cases/{case_id}/timeline").json() == {"events": []}
    assert client.get(f"/api/network/{case_id}/coverage").json() is None


@pytest.mark.parametrize("path", ["/api/cases/{}/provenance", "/api/cases/{}/timeline", "/api/network/{}/coverage"])
def test_unknown_case_is_not_found(path):
    assert client.get(path.format("unknown")).status_code == 404


# Timeline


def test_timeline_is_ordered_and_keeps_undated_events(outside):
    _, results = outside
    results["search"] = lambda: report(
        appearance(1, observed_at=datetime(2022, 1, 1, tzinfo=UTC)),
        appearance(2),
        appearance(3, observed_at=datetime(2020, 1, 1, tzinfo=UTC)),
    )
    case_id = client.post(MEDIA_UPLOAD_PATH, files=MEDIA_FIELDS, data={"search_web": "true"}).json()["case_id"]
    events = client.get(f"/api/cases/{case_id}/timeline").json()["events"]
    assert [event["ref"] for event in events] == ["a3", "a1", "a2"]
    assert events[-1]["at"] is None
    assert events[-1]["date_source"] == "none"
    assert {event["module"] for event in events} == {"provenance"}


def test_demo_timeline_combines_both_modules_and_is_labelled():
    events = client.get("/api/cases/demo-001/timeline").json()["events"]
    assert {event["module"] for event in events} == {"provenance", "network"}
    assert {event["kind"] for event in events} == {"web_appearance", "cluster_activity"}
    assert all(event["synthetic"] for event in events)
    dated = [event["at"] for event in events if event["at"]]
    assert dated == sorted(dated, key=datetime.fromisoformat)


def test_timeline_never_calls_a_post_the_source():
    submission = get_demo_story()["submission"]
    case_id = client.post("/api/cases/analyze", json={**submission, "search_web": True}).json()["case_id"]
    labels = " ".join(event["label"] for event in client.get(f"/api/cases/{case_id}/timeline").json()["events"])
    assert "Earliest matching post these searches found" in labels
    assert "source" not in labels.lower()
    assert "original" not in labels.lower()


# Saved details outlive this process


def test_details_are_read_back_after_a_restart(monkeypatch, tmp_path):
    """A new process has an empty trace cache, but the case store still has the details."""
    monkeypatch.setattr(main, "CASE_STORE", CaseStore(tmp_path / "cases.db"))
    submission = get_demo_story()["submission"]
    case_id = client.post("/api/cases/analyze", json={**submission, "search_web": True}).json()["case_id"]
    before = {
        path: client.get(path).json()
        for path in (
            f"/api/network/{case_id}",
            f"/api/network/{case_id}/coverage",
            f"/api/cases/{case_id}/timeline",
            f"/api/cases/{case_id}",
        )
    }

    monkeypatch.setattr(main, "CASES", {})
    monkeypatch.setattr(main, "get_network_payload", lambda _: None)
    monkeypatch.setattr(main, "CASE_STORE", CaseStore(tmp_path / "cases.db"))
    for path, body in before.items():
        assert client.get(path).json() == body, path


def test_store_keeps_details_per_case_and_clears_them(tmp_path):
    store = CaseStore(tmp_path / "cases.db")
    store.save_detail("a", "network", {"value": 1})
    store.save_detail("a", "network", {"value": 2})
    store.save_detail("b", "network", {"value": 3})
    assert store.get_detail("a", "network") == {"value": 2}
    assert store.get_detail("a", "provenance") is None
    store.clear()
    assert store.get_detail("b", "network") is None
