"""Claim analysis through the HTTP API."""

from fastapi.testclient import TestClient

from backend.api.app.main import app
from backend.api.app.models import AnalysisResponse
from backend.text import ner

client = TestClient(app)


def analyze(text):
    return client.post("/api/cases/analyze", json={"text": text}).json()


def test_claims_carry_kinds_and_entities():
    body = analyze("Share this now! At least 50 people died on 5 March 2024.")
    first, second = body["claims"]
    assert (first["kind"], first["checkable"]) == ("call_to_action", False)
    assert (second["kind"], second["checkable"]) == ("factual", True)
    assert second["verdict"] == "unverified"
    entities = {item["type"]: item for item in second["entities"]}
    assert entities["date"]["value"] == "2024-03-05"
    assert (entities["number"]["value"], entities["number"]["unit"], entities["number"]["bound"]) == ("50", "people", "at_least")


def test_missing_model_says_unavailable_with_the_reason():
    analysis = analyze("The bridge collapsed near the station.")["claim_analysis"]
    assert analysis["entity_model_status"] == "unavailable"
    assert ner.MODEL_ID in analysis["entity_model_reason"]
    assert "download-ner" in analysis["entity_model_reason"]


def test_inconsistency_is_reported_as_evidence_and_does_not_change_the_score():
    text = "The factory fire killed 50 people. The factory fire killed 200 people."
    body = analyze(text)
    items = body["claim_analysis"]["inconsistencies"]
    assert [(item["kind"], item["severity"], item["claim_ids"]) for item in items] == [
        ("figures", "conflict", ["claim-1", "claim-2"])
    ]
    assert any("Possible inconsistency" in line for line in body["modules"]["text"]["evidence"])
    assert body["modules"]["text"]["score"] == 0


def test_no_text_means_no_claim_analysis():
    body = client.post("/api/cases/analyze", json={"url": "https://example.com/a"}).json()
    assert body["claims"] == []
    assert body["claim_analysis"] is None


def test_cases_saved_before_these_fields_still_load():
    old = {
        "case_id": "old",
        "overall_risk": "low",
        "summary": "s",
        "modules": {},
        "claims": [{"id": "claim-1", "text": "An old claim."}],
    }
    case = AnalysisResponse.model_validate(old)
    assert case.claim_analysis is None
    assert case.claims[0].entities == []
    assert case.claims[0].checkable is True
