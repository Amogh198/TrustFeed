"""Scam analysis through the HTTP API."""

from fastapi.testclient import TestClient

from backend.api.app import scam_records
from backend.api.app.main import app
from backend.api.app.models import AnalysisResponse
from backend.text.scam_model import PhishingOutcome

client = TestClient(app)
SCAM = "Your account has been compromised. Reply with the OTP we just sent you."


def analyze(text):
    return client.post("/api/cases/analyze", json={"text": text}).json()


def test_signs_are_named_with_reasons_and_quotes():
    scams = analyze(SCAM)["scam_analysis"]
    assert scams["assessment"] == "warning_signs_found"
    assert "credential_request" in scams["categories"]
    sign = next(item for item in scams["signs"] if item["sign"] == "credential_request")
    assert sign["why"] and sign["strength"] == "strong"
    assert "OTP" in sign["quote"]
    assert any("does not mean something is safe" in item for item in scams["limitations"])


def test_signs_appear_as_evidence_and_advice_without_changing_the_score():
    body = analyze("Please reply with the password for your mailbox today.")
    plain = analyze("Please reply today about the meeting at the office.")
    assert any("Scam warning sign" in line for line in body["modules"]["text"]["evidence"])
    assert any("Do not pay" in line for line in body["recommended_actions"])
    assert not any("Do not pay" in line for line in plain["recommended_actions"])
    assert body["modules"]["text"]["score"] == plain["modules"]["text"]["score"]


def test_nothing_found_is_never_called_safe():
    scams = analyze("The bridge was repainted last spring.")["scam_analysis"]
    assert scams["assessment"] == "none_found"
    assert scams["signs"] == []
    assert "safe" not in scams["assessment"]


def test_model_is_off_by_default_and_says_why(monkeypatch):
    def forbidden():
        raise AssertionError("The model ran while turned off")

    monkeypatch.delenv("TEXT_SCAM_MODEL_ENABLED", raising=False)
    monkeypatch.setattr(scam_records, "default_runner", forbidden)
    scams = analyze(SCAM)["scam_analysis"]
    assert scams["model_status"] == "unavailable"
    assert "too many legitimate posts" in scams["model_reason"]
    assert scams["results_file"] in scams["model_reason"]
    assert scams["model_score"] is None


def test_model_score_when_turned_on_never_changes_the_assessment(monkeypatch):
    class Runner:
        def run(self, text):
            return PhishingOutcome("complete", score=0.99)

    monkeypatch.setenv("TEXT_SCAM_MODEL_ENABLED", "1")
    monkeypatch.setattr(scam_records, "default_runner", Runner)
    scams = analyze("The bridge was repainted last spring.")["scam_analysis"]
    assert (scams["model_status"], scams["model_score"], scams["assessment"]) == ("complete", 0.99, "none_found")


def test_no_text_means_no_scam_analysis():
    assert client.post("/api/cases/analyze", json={"url": "https://example.com/a"}).json()["scam_analysis"] is None


def test_cases_saved_earlier_still_load():
    case = AnalysisResponse.model_validate({"case_id": "old", "overall_risk": "low", "summary": "s", "modules": {}})
    assert case.scam_analysis is None
