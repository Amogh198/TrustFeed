"""Explanation, monitoring, heatmap, demo cases, and the stronger text and link rules. No network."""

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import backend.api.app.main as main_module
from backend.api.app.explanation import build_countermeasures
from backend.api.app.fusion import disagreement_note
from backend.api.app.main import app
from backend.api.app.models import RiskLevel
from backend.media.heatmap import OcclusionHeatmap
from backend.media.models import CheckStatus
from backend.network import list_watches, stop_watch
from backend.provenance.safe_http import HttpFailed
from backend.text.analysis import analyze_text, analyze_url, expand_shortener, fuse_risk

client = TestClient(app)


def png_bytes(size=(128, 128)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (90, 120, 150)).save(buffer, "PNG")
    return buffer.getvalue()


# Text rules


@pytest.mark.parametrize(
    "text",
    [
        "You have won a prize! Click here to claim your reward and enter your bank OTP immediately.",
        "Send 5000 rupees today to double your money, guaranteed returns, limited time offer!",
        "Drinking bleach cures the virus, doctors do not want you to know this.",
    ],
)
def test_obvious_scam_and_health_patterns_are_not_low(text):
    result, _ = analyze_text(text)
    assert fuse_risk(result, None) in (RiskLevel.MODERATE, RiskLevel.HIGH)


def test_indic_language_phrases_are_found():
    result, _ = analyze_text("पानी में जहर मिला दिया गया है, यह संदेश सबको तुरंत भेजें!")
    assert result.score and result.score > 0
    assert any("तुरंत" in line for line in result.evidence)


@pytest.mark.parametrize(
    "text",
    [
        "The city council meets on Tuesday to discuss the new library budget.",
        "A hotpot restaurant opened near the insurgent museum exhibit.",
        "The council is breaking ground on a new school this spring.",
    ],
)
def test_ordinary_text_is_not_raised_above_low(text):
    result, _ = analyze_text(text)
    assert fuse_risk(result, None) is RiskLevel.LOW


def test_words_inside_other_words_do_not_match():
    result, _ = analyze_text("A hotpot restaurant opened near the insurgent museum exhibit.")
    assert result.evidence == []


def test_rules_alone_never_reach_critical():
    result, _ = analyze_text(
        "URGENT BREAKING act now! You have won! Claim your prize, send your password and OTP. "
        "Officials are hiding the truth!!! Miracle cure!"
    )
    assert fuse_risk(result, None) is not RiskLevel.CRITICAL


# Link rules


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.10.5/login/verify-account",
        "http://secure-paypal.com.account-verify.example/login",
        "https://g00gle-login.example/verify",
        "https://paypal-secure.example/account",
    ],
)
def test_phishing_style_links_are_not_low(url):
    assert fuse_risk(None, analyze_url(url)) in (RiskLevel.MODERATE, RiskLevel.HIGH)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.paypal.com/signin",
        "https://accounts.google.com/login",
        "https://www.sbi.co.in/",
        "https://www.who.int/news",
        "https://en.wikipedia.org/wiki/Flood",
        "https://www.bbc.com/news",
    ],
)
def test_real_sites_are_not_flagged(url):
    result = analyze_url(url)
    assert result.score == 0, result.evidence


def test_short_link_is_followed_only_through_the_given_request():
    class Response:
        url = "https://paypal-secure.example/login"

    assert expand_shortener("https://bit.ly/abc", request=lambda *_a, **_k: Response()) == Response.url
    assert expand_shortener("https://example.org/abc", request=lambda *_a, **_k: Response()) is None


def test_a_failed_expansion_is_scored_without_the_destination():
    def fail(*_args, **_kwargs):
        raise HttpFailed("timeout")

    assert expand_shortener("https://bit.ly/abc", request=fail) is None


def test_expanded_destination_is_scored_and_named():
    result = analyze_url("https://bit.ly/abc", expanded_to="https://paypal-secure.example/login")
    assert any("paypal-secure.example" in line for line in result.evidence)
    assert any("does not belong" in line for line in result.evidence)


def test_short_links_are_not_followed_without_opt_in(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("A link must not be followed without opt-in")

    monkeypatch.setattr(main_module, "expand_shortener", refuse)
    body = client.post("/api/cases/analyze", json={"url": "https://bit.ly/abc"}).json()
    assert any("not followed" in line for line in body["modules"]["url"]["evidence"])


# Fusion


def test_a_quiet_detector_is_inconclusive_and_says_why(monkeypatch):
    from backend.media.models import Assessment

    original = main_module.analyze_media

    def quiet(path):
        result = original(path)
        return result.model_copy(update={"assessment": Assessment.NO_STRONG_SIGNALS, "failure_code": None})

    monkeypatch.setattr(main_module, "analyze_media", quiet)
    body = client.post("/api/cases/analyze-media", files={"file": ("a.png", png_bytes(), "image/png")}).json()
    assert body["overall_risk"] == "inconclusive"
    assert any("does not show the media is authentic" in line for line in body["uncertainties"])


def test_disagreement_is_named_only_when_two_levels_apart():
    note = disagreement_note({"the text check": RiskLevel.HIGH, "the link check": RiskLevel.LOW})
    assert note is not None
    assert "the text check" in note
    assert "the link check" in note
    assert disagreement_note({"a": RiskLevel.MODERATE, "b": RiskLevel.LOW}) is None
    assert disagreement_note({"a": RiskLevel.HIGH, "b": RiskLevel.INCONCLUSIVE}) is None


def test_case_reports_disagreement_between_checks():
    body = client.post(
        "/api/cases/analyze",
        json={"text": "A community meeting is on Friday.", "url": "http://secure-paypal.com.account-verify.example/login"},
    ).json()
    assert any("checks disagree" in line for line in body["uncertainties"])


# Explanation


def explanation(case_id):
    response = client.get(f"/api/cases/{case_id}/explanation")
    assert response.status_code == 200, response.text
    return response.json()


def test_text_case_explains_its_checks_and_lists_what_did_not_run():
    case = client.post("/api/cases/analyze", json={"text": "Urgent! Claim your prize now."}).json()
    body = explanation(case["case_id"])
    assert body["what_was_submitted"] == ["Text"]
    assert "Text" not in " ".join(body["what_was_detected"]) or body["what_was_detected"]
    assert [check["check_id"] for check in body["checks"]] == ["text.rules"]
    assert body["checks"][0]["benchmark"] is None
    assert any("scam-pattern" in line for line in body["supports"])
    assert {item["module"] for item in body["missing_checks"]} == {"url", "media", "provenance", "network"}


def test_explanation_never_repeats_submitted_text_as_a_summary():
    secret = "my-private-marker-text that is long enough"
    case = client.post("/api/cases/analyze", json={"text": secret}).json()
    assert secret not in " ".join(explanation(case["case_id"])["what_was_submitted"])


def test_demo_explanation_merges_source_search_and_network_checks():
    body = explanation("demo-001")
    ids = {check["check_id"] for check in body["checks"]}
    assert {"network.platform_search", "network.coordination_signal"} <= ids
    assert any(check["module"] == "provenance" for check in body["checks"])
    assert all(check["benchmark"] is None for check in body["checks"])
    assert body["what_was_submitted"] == ["No content was submitted. This is a demonstration case."]


def test_upload_explanation_includes_media_checks_after_the_file_is_gone():
    case = client.post("/api/cases/analyze-media", files={"file": ("a.png", png_bytes(), "image/png")}).json()
    ids = {check["check_id"] for check in explanation(case["case_id"])["checks"]}
    assert {"media.classifier", "media.metadata", "media.phash", "media.keyframes"} <= ids


def test_unknown_case_has_no_explanation():
    assert client.get("/api/cases/no-such-case/explanation").status_code == 404


# Demo cases


def test_demo_cases_are_labelled_in_the_case_itself():
    for case_id in ("demo-001", "demo-story-001"):
        body = client.get(f"/api/cases/{case_id}").json()
        assert body["is_replay"] is True
        assert "SYNTHETIC" in body["replay_label"]


def test_linked_story_is_a_whole_offline_case():
    body = client.get("/api/cases/demo-story-001").json()
    assert body["modules"]["network"]["status"] == "complete"
    assert body["modules"]["text"]["status"] == "complete"
    assert body["claims"]
    assert client.get("/api/cases/demo-story-001/timeline").status_code == 200
    assert client.get("/api/cases/demo-story-001/export").status_code == 200
    assert client.post("/api/cases/demo-story-001/action-packet", json={}).status_code == 200
    checks = {check["check_id"] for check in explanation("demo-story-001")["checks"]}
    assert {"text.rules", "url.rules", "network.matching_posts"} <= checks


# Countermeasures


def test_countermeasures_follow_what_the_case_shows():
    scam = client.post("/api/cases/analyze", json={"text": "You have won! Send your OTP now."}).json()
    packet = client.post(f"/api/cases/{scam['case_id']}/action-packet", json={}).json()
    section = next(item for item in packet["sections"] if item["heading"] == "Suggested countermeasures")
    assert any("one-time codes" in line for line in section["items"])
    assert packet["generated"] is False
    plain = main_module.CASE_STORE.get(client.post("/api/cases/analyze", json={"text": "The library opens at nine."}).json()["case_id"])
    assert plain is not None
    assert not any("one-time codes" in line for line in build_countermeasures(plain))


def test_quiet_media_countermeasure_warns_against_trusting_a_low_score():
    demo = client.get("/api/cases/demo-001").json()
    packet = client.post("/api/cases/demo-001/action-packet", json={}).json()
    section = next(item for item in packet["sections"] if item["heading"] == "Suggested countermeasures")
    assert any("not proof of coordination" in line for line in section["items"])
    assert demo["modules"]["media"]["status"] == "not_applicable"


# Monitoring


@pytest.fixture
def no_watches():
    yield
    for watch_id in list_watches():
        stop_watch(watch_id)


def test_monitor_needs_opt_in_and_sends_nothing_when_refused(no_watches):
    response = client.post("/api/monitors", json={"opted_in": False, "hashtags": ["floods"]})
    assert response.status_code == 422
    assert "opt-in" in response.json()["detail"]["message"]
    assert client.get("/api/monitors").json()["watches"] == []


def test_monitor_needs_something_to_watch(no_watches):
    assert client.post("/api/monitors", json={"opted_in": True}).status_code == 422


def test_monitor_refuses_in_replay_mode(no_watches, monkeypatch):
    monkeypatch.setenv("PROVENANCE_REPLAY_PATH", "recording.json")
    response = client.post("/api/monitors", json={"opted_in": True, "hashtags": ["floods"]})
    assert response.status_code == 409


def test_monitor_starts_polls_limits_and_stops(no_watches, monkeypatch):
    # A fake poll, so that this test stays offline.
    monkeypatch.setattr(main_module, "poll_watch", lambda watch_id: {"watch_id": watch_id, "poll": 1})
    started = client.post("/api/monitors", json={"opted_in": True, "hashtags": ["floods"]}).json()
    watch_id = started["watch_id"]
    assert started["min_poll_interval_seconds"] == 60
    assert client.get("/api/monitors").json()["watches"] == [watch_id]
    assert client.post(f"/api/monitors/{watch_id}/poll").json()["poll"] == 1
    assert client.delete(f"/api/monitors/{watch_id}").json() == {"stopped": True}
    assert client.post(f"/api/monitors/{watch_id}/poll").status_code == 404


def test_monitor_allows_delete_from_the_dashboard():
    response = client.options(
        "/api/monitors/x",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "DELETE"},
    )
    assert response.status_code == 200
    assert "DELETE" in response.headers["access-control-allow-methods"]


# Heatmap


def test_heatmap_returns_a_colour_grid_and_its_limits(monkeypatch):
    result = OcclusionHeatmap(
        status=CheckStatus.COMPLETE,
        base_score=0.4,
        changes=[[0.1] * 8 for _ in range(8)],
        max_change=0.1,
        notable=True,
        reasoning="Some areas moved the score.",
        limitations=["This shows sensitivity."],
    )
    monkeypatch.setattr(main_module, "occlusion_heatmap", lambda *_a, **_k: result)
    monkeypatch.setattr(main_module, "default_classifier", lambda _config: object())
    response = client.post("/api/media/heatmap", files={"file": ("a.png", png_bytes(), "image/png")})
    assert response.status_code == 200
    body = response.json()
    assert "not proof of editing" in body["label"]
    assert base64.b64decode(body["png_base64"]).startswith(b"\x89PNG")


def test_heatmap_says_when_it_cannot_run(monkeypatch):
    unavailable = OcclusionHeatmap(status=CheckStatus.UNAVAILABLE, reasoning="The model is not installed.")
    monkeypatch.setattr(main_module, "occlusion_heatmap", lambda *_a, **_k: unavailable)
    monkeypatch.setattr(main_module, "default_classifier", lambda _config: object())
    body = client.post("/api/media/heatmap", files={"file": ("a.png", png_bytes(), "image/png")}).json()
    assert body["status"] == "unavailable"
    assert body["png_base64"] is None


def test_heatmap_rejects_files_that_are_not_images():
    response = client.post("/api/media/heatmap", files={"file": ("a.txt", b"hello", "text/plain")})
    assert response.status_code in (415, 422)
    assert response.json()["detail"]["code"]


def test_heatmap_runs_one_at_a_time():
    assert main_module._heatmap_slot.acquire(blocking=False)
    try:
        response = client.post("/api/media/heatmap", files={"file": ("a.png", png_bytes(), "image/png")})
    finally:
        main_module._heatmap_slot.release()
    assert response.status_code == 429
