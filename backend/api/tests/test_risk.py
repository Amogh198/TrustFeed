"""Unified risk through the API and directly."""

import pytest
from fastapi.testclient import TestClient

from backend.api.app.main import app
from backend.api.app.models import ModuleResult, ModuleStatus, RiskLevel
from backend.api.app.risk import build_unified_risk, load_weights

client = TestClient(app)
SCAM = "Pay a registration fee of Rs 500 to get this work from home job. Send your OTP now to claim your prize."


def build(**given):
    return build_unified_risk(
        **{
            "text": None, "url": None, "media": None, "network": None, "claims": None,
            "claim_analysis": None, "scam_analysis": None, "link_analysis": None, "cross_modal": None, **given,
        }
    )


def media(score):
    return ModuleResult(status=ModuleStatus.COMPLETE, score=score, evidence=["e"])


def test_high_score_with_an_unclear_assessment_is_not_counted():
    assert build(media=media(0.99), media_level=RiskLevel.INCONCLUSIVE).level is RiskLevel.INCONCLUSIVE


def components(body):
    return {item["name"]: item for item in body["unified_risk"]["components"]}


def test_nothing_measured_is_inconclusive_with_no_trust_score():
    risk = build()
    assert risk.level is RiskLevel.INCONCLUSIVE and risk.trust_score is None and risk.score is None


def test_quiet_media_alone_is_inconclusive_not_low():
    risk = build(media=media(0.01))
    assert risk.level is RiskLevel.INCONCLUSIVE and risk.trust_score is None


def test_missing_media_never_reads_as_a_low_score():
    risk = build(media=ModuleResult(status=ModuleStatus.UNAVAILABLE, limitations=["No model."]))
    assert risk.level is RiskLevel.INCONCLUSIVE


def test_one_model_never_reaches_critical():
    risk = build(media=media(0.99), media_level=RiskLevel.HIGH)
    assert risk.level is RiskLevel.HIGH and risk.trust_score == 25


def test_lookalike_link_is_scored_and_trust_stays_capped():
    body = client.post("/api/cases/analyze", json={"url": "https://paypa1.com/a"}).json()
    assert body["overall_risk"] == "high" == body["unified_risk"]["level"]
    assert components(body)["link"]["counted"] and components(body)["link"]["results_file"]
    assert body["unified_risk"]["trust_score"] <= 25


def test_two_measured_signals_reach_critical():
    body = client.post("/api/cases/analyze", json={"text": SCAM, "url": "https://paypa1.com/a"}).json()
    assert body["overall_risk"] == "critical"


def test_clean_text_and_link_read_low_and_never_above_fifty():
    body = client.post(
        "/api/cases/analyze", json={"text": "The library opens at nine on weekdays.", "url": "https://example.org/hours"}
    ).json()
    assert body["overall_risk"] == "low"
    assert body["unified_risk"]["trust_score"] == 50


def test_language_rule_alone_is_shown_not_scored_and_blocks_low():
    body = client.post("/api/cases/analyze", json={"text": "Officials are hiding the truth about this."}).json()
    language = components(body)["language"]
    assert language["evidence"] and not language["counted"] and "measured" in language["note"]
    assert body["overall_risk"] == "inconclusive"
    assert "Language rules" in body["summary"]


@pytest.mark.parametrize("name", ["claims", "inconsistency", "cross_modal", "spread"])
def test_unmeasured_components_are_never_counted(name):
    body = client.post("/api/cases/analyze", json={"text": "The library opens at nine."}).json()
    assert components(body)[name]["counted"] is False


def test_weights_are_configurable_and_bad_values_are_ignored(monkeypatch):
    assert load_weights('{"media": 0.5, "scam": 7, "link": true, "other": 1}') == {"media": 0.5, "scam": 1.0, "link": 1.0}
    assert load_weights("not json")["media"] == 1.0
    monkeypatch.setenv("RISK_WEIGHTS", '{"link": 0}')
    body = client.post("/api/cases/analyze", json={"url": "https://paypa1.com/a"}).json()
    # With the score at zero, the unscored link rule still stops it reading Low.
    assert body["unified_risk"]["score"] == 0 and body["overall_risk"] == "inconclusive" and components(body)["link"]["weight"] == 0
