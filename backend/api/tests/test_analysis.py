from fastapi.testclient import TestClient

from backend.api.app.main import app
from backend.api.app.models import RiskLevel
from backend.provenance.safe_http import HttpResponse
from backend.text.analysis import analyze_text, analyze_url, expand_short_url, fuse_risk

client = TestClient(app)


def test_text_analysis_reports_matching_evidence_and_limits_claims():
    result, claims = analyze_text("Urgent! Forward this now to claim your prize!!!")

    assert result.score is not None and result.score > 0
    assert any("Urgency" in item for item in result.evidence)
    assert any("scam-pattern" in item for item in result.evidence)
    assert result.confidence is None
    assert claims == ["Urgent!", "Forward this now to claim your prize!!!"]
    assert "do not verify" in result.limitations[0]


def test_plain_text_has_zero_signal_score_not_a_factual_verdict():
    result, _ = analyze_text("A community meeting will happen on Friday.")

    assert result.score == 0
    assert result.evidence == []
    assert result.confidence is None


def test_url_analysis_is_static_and_marks_shorteners():
    result = analyze_url("http://bit.ly/example")

    assert result.score is not None and result.score > 0
    assert any("HTTPS" in item for item in result.evidence)
    assert any("shortening" in item for item in result.evidence)
    assert "no domain reputation" in result.limitations[0]


def test_shortener_expansion_is_safe_and_opt_in_ready(monkeypatch):
    monkeypatch.setattr(
        "backend.text.analysis.safe_request",
        lambda *args, **kwargs: HttpResponse(url="https://example.zip/login", status=200),
    )

    expanded, limit = expand_short_url("https://bit.ly/demo")
    result = analyze_url("https://bit.ly/demo", expanded_url=expanded, expansion_limit=limit)

    assert expanded == "https://example.zip/login"
    assert limit is None
    assert any("resolved" in item for item in result.evidence)
    assert any("deceptive links" in item for item in result.evidence)


def test_risk_is_inconclusive_without_module_scores():
    assert fuse_risk(None, None) == RiskLevel.INCONCLUSIVE


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyze_and_retrieve_case():
    response = client.post(
        "/api/cases/analyze",
        json={"text": "Urgent, act now and verify your account"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"]
    assert body["modules"]["text"]["status"] == "complete"
    assert body["modules"]["media"]["status"] == "not_applicable"
    assert body["modules"]["network"]["status"] == "unavailable"
    assert client.get(f"/api/cases/{body['case_id']}").json() == body


def test_analyze_rejects_empty_input():
    response = client.post("/api/cases/analyze", json={})

    assert response.status_code == 422
