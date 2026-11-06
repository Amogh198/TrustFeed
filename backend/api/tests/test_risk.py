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


def test_high_score_with_an_unclear_assessment_stays_a_weak_signal():
    assert build(media=media(0.99), media_level=RiskLevel.INCONCLUSIVE).level is RiskLevel.MODERATE


def components(body):
    return {item["name"]: item for item in body["unified_risk"]["components"]}


def test_nothing_measured_is_inconclusive_with_no_trust_score():
    risk = build()
    assert risk.level is RiskLevel.INCONCLUSIVE and risk.trust_score is None and risk.score is None


def test_quiet_media_alone_is_inconclusive_not_low():
    risk = build(media=media(0.001))
    assert risk.level is RiskLevel.INCONCLUSIVE and risk.trust_score is None


def test_media_above_the_review_line_is_a_weak_signal_that_says_its_error_rate():
    risk = build(media=media(0.01), media_level=RiskLevel.INCONCLUSIVE)
    assert risk.level is RiskLevel.MODERATE and risk.trust_score == 40
    assert "19% of real images" in risk.components[0].note


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
    assert body["unified_risk"]["score"] == 0 and body["overall_risk"] == "low" and components(body)["link"]["weight"] == 0


def test_a_live_check_that_failed_cannot_read_as_low(monkeypatch):
    from backend.api.app import main

    real = main.investigate_link

    def crash(url, *, offline_reason=None, **_kw):
        if offline_reason is None:
            raise ValueError("broken")
        return real(url, offline_reason=offline_reason)

    monkeypatch.setattr(main, "investigate_link", crash)
    monkeypatch.setattr(main, "trace_case", lambda *_a, **_k: {"status": "complete", "score": None, "confidence": None, "evidence": []})
    body = client.post("/api/cases/analyze", json={"url": "https://example.org/", "search_web": True}).json()
    assert body["overall_risk"] == "inconclusive"
    assert "Could not finish" in components(body)["link"]["note"]


def test_an_offline_check_by_choice_can_read_low():
    body = client.post("/api/cases/analyze", json={"url": "https://example.org/"}).json()
    assert body["overall_risk"] == "low" and not body["link_analysis"]["live_failed"]


@pytest.mark.parametrize(
    "url",
    ["https://free-gift-claim.top/", "http://192.0.2.7/login.php", "https://bit.ly/abc", "https://lucky-prize-winner.example/x", "https://xn--pypal-4ve.com/", "https://login-check.pages.dev/", "https://portail-mlcrosoft.fr/"],
)
def test_dangerous_links_outside_the_brand_list_are_not_scored_as_nothing(url):
    body = client.post("/api/cases/analyze", json={"url": url}).json()
    assert body["overall_risk"] in {"moderate", "high", "critical"}
    assert body["unified_risk"]["trust_score"] <= 40


def test_a_link_on_a_threat_feed_is_critical(monkeypatch):
    from backend.api.app import main
    from backend.provenance.safe_http import HttpResponse
    from backend.text.links import ThreatFeeds

    feed = HttpResponse(url="", status=200, body=b"# comment\nhttp://bad.example/payload.exe\n")
    feeds = ThreatFeeds({"TestFeed": "https://feed.example/"})
    real = main.investigate_link
    monkeypatch.setattr(main, "DEFAULT_FEEDS", feeds)
    monkeypatch.setenv("LINK_THREAT_FEEDS", "on")
    monkeypatch.setattr(main, "investigate_link", lambda url, **kw: real(url, request=lambda *_a, **_k: feed, **kw))
    listed = client.post("/api/cases/analyze", json={"url": "http://bad.example/payload.exe"}).json()
    assert listed["overall_risk"] == "critical" and listed["link_analysis"]["threat_lists"]["listed"]
    assert listed["unified_risk"]["trust_score"] <= 25
    host = client.post("/api/cases/analyze", json={"url": "http://bad.example/other"}).json()
    assert host["overall_risk"] == "high"
    clean = client.post("/api/cases/analyze", json={"url": "https://town-notices.example/"}).json()
    assert clean["overall_risk"] == "low" and clean["link_analysis"]["threat_lists"]["status"] == "complete"


def test_unreadable_feeds_say_so_and_retry_later():
    from backend.provenance.safe_http import HttpFailed
    from backend.text.links import ThreatFeeds

    def fail(*_a, **_k):
        raise HttpFailed("network")

    result, signs = ThreatFeeds({"TestFeed": "https://feed.example/"}).check(["https://a.example/"], fail)
    assert result.status is ModuleStatus.UNAVAILABLE and signs == []


def test_a_host_only_feed_flags_the_host_but_not_a_brands_own_site():
    from backend.provenance.safe_http import HttpResponse
    from backend.text.links import ThreatFeeds

    feed = HttpResponse(url="", status=200, body=b"# comment\nbad-host.example\nsites.google.com\n")
    feeds = ThreatFeeds({"TestFeed": "https://feed.example/"})
    result, signs = feeds.check(["https://bad-host.example/a"], lambda *_a, **_k: feed)
    assert result.entries == 2 and [sign.sign for sign in signs] == ["threat_host_listed"]
    assert feeds.check(["https://sites.google.com/view/x"], lambda *_a, **_k: feed)[1] == []
