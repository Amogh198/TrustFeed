"""Claim verification through the HTTP API. All network and model calls are faked."""

import pytest
from fastapi.testclient import TestClient

from backend.api.app import claim_records, main
from backend.api.app.main import app
from backend.api.app.models import AnalysisResponse
from backend.text import verification
from backend.text.evidence_sources import Document, ProviderResult
from backend.text.verify_models import Entailment

client = TestClient(app)
PASSAGE = "The Sector 9 bridge collapsed in 2024 after heavy rain, officials confirmed."


class Provider:
    name = "fake"

    def search(self, query, deadline):
        return ProviderResult(
            self.name,
            "complete",
            documents=[
                Document("fake", "A", "https://a.example/1", "a.example", PASSAGE, "2024-03-05T00:00:00Z", "first_seen"),
                Document("fake", "B", "https://b.example/1", "b.example", f"Inspectors reported this: {PASSAGE}"),
            ],
        )


class Comparer:
    def is_ready(self):
        return None

    def similarity(self, claim, passages):
        return [0.9 for _ in passages]

    def entail(self, pairs):
        return [Entailment(0.95, 0.03, 0.02) for _ in pairs]


@pytest.fixture
def fakes(monkeypatch):
    monkeypatch.delenv("PROVENANCE_REPLAY_PATH", raising=False)
    monkeypatch.setattr(verification, "default_providers", lambda: [Provider()])
    monkeypatch.setattr(verification, "_default_comparer", lambda: Comparer())
    # The public-post trace is another lane's and has its own tests.
    monkeypatch.setattr(main, "trace_case", lambda *args, **kwargs: {"status": "unavailable", "limitations": ["Skipped."]})


def test_without_search_web_nothing_is_searched(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Claim verification ran without the user's consent")

    monkeypatch.setattr(claim_records, "verify_claims", forbidden)
    body = client.post("/api/cases/analyze", json={"text": "The Sector 9 bridge collapsed in 2024."}).json()
    claim = body["claims"][0]
    assert claim["verdict"] == "unverified"
    assert claim["sources"] == []
    assert "No external evidence" in claim["rationale"]
    state = body["claim_analysis"]["verification"]
    assert state["status"] == "not_applicable"
    assert "no claim was sent" in state["reason"]
    assert "No external fact-checking or domain reputation source was queried." in body["uncertainties"]


def test_with_search_web_each_claim_shows_links_dates_and_why(fakes):
    body = client.post(
        "/api/cases/analyze", json={"text": "The Sector 9 bridge collapsed in 2024.", "search_web": True}
    ).json()
    claim = body["claims"][0]
    assert claim["verdict"] == "supported"
    assert "a.example" in claim["rationale"]
    first = claim["sources"][0]
    assert (first["url"], first["date"], first["date_kind"], first["stance"]) == (
        "https://a.example/1", "2024-03-05T00:00:00Z", "first_seen", "supports",
    )
    assert first["explanation"] and first["snippet"]
    state = body["claim_analysis"]["verification"]
    assert (state["status"], state["comparison_status"]) == ("complete", "complete")
    assert state["providers"] == [{"name": "fake", "status": "complete", "reason": None, "result_count": 2}]
    assert "No external fact-checking or domain reputation source was queried." not in body["uncertainties"]


def test_a_verdict_does_not_change_the_score_or_risk(fakes):
    text = "The Sector 9 bridge collapsed in 2024."
    plain = client.post("/api/cases/analyze", json={"text": text}).json()
    searched = client.post("/api/cases/analyze", json={"text": text, "search_web": True}).json()
    assert searched["claims"][0]["verdict"] != plain["claims"][0]["verdict"]
    assert searched["overall_risk"] == plain["overall_risk"]
    assert searched["modules"]["text"]["score"] == plain["modules"]["text"]["score"]


def test_labelled_demo_story_never_reaches_outside_services(fakes, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The synthetic demo story was sent to an outside service")

    monkeypatch.setattr(claim_records, "verify_claims", forbidden)
    monkeypatch.setattr(main, "_network_detail", lambda case_id: {"payload": {"timeline": []}, "coverage": {"synthetic": True}})
    body = client.post("/api/cases/analyze", json={"text": "An invented story for the demo.", "search_web": True}).json()
    state = body["claim_analysis"]["verification"]
    assert state["status"] == "not_applicable"
    assert "stays offline" in state["reason"]
    assert body["claims"][0]["verdict"] == "unverified"


def test_saved_case_keeps_its_sources(fakes):
    body = client.post(
        "/api/cases/analyze", json={"text": "The Sector 9 bridge collapsed in 2024.", "search_web": True}
    ).json()
    main.CASES.pop(body["case_id"], None)
    saved = client.get(f"/api/cases/{body['case_id']}").json()
    assert saved["claims"][0]["sources"][0]["url"] == "https://a.example/1"


def test_cases_saved_earlier_still_load():
    case = AnalysisResponse.model_validate(
        {
            "case_id": "old", "overall_risk": "low", "summary": "s", "modules": {},
            "claims": [{"id": "claim-1", "text": "Old."}],
            "claim_analysis": {"entity_model_status": "unavailable"},
        }
    )
    assert case.claims[0].sources == []
    assert case.claim_analysis.verification.status == "not_applicable"
