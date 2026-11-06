from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.api.app.main import app

client = TestClient(app)


def test_monitor_alerts_returns_active_campaigns():
    response = client.get("/api/monitor/alerts")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    top = data[0]
    assert "campaign_id" in top
    assert "platform_spread" in top
    assert "total_posts" in top
    assert "risk_level" in top
    assert isinstance(top["platform_spread"], list)
    assert isinstance(top["total_posts"], int)
    assert top["risk_level"] in {"low", "moderate", "high", "critical", "inconclusive"}


def test_monitor_alerts_list_the_earliest_post_on_each_platform_from_the_data():
    top = client.get("/api/monitor/alerts").json()[0]
    steps = top["spread_steps"]
    assert {step["platform"] for step in steps} == set(top["platform_spread"])
    seconds = [step["seconds_after_first"] for step in steps]
    assert seconds[0] == 0 and seconds == sorted(seconds)
    assert all(step["handle"] and step["first_seen_at"] for step in steps)
    # Scores and similarity figures belong to real checks, not to this replay feed.
    assert "deepfake_score" not in steps[0] and "similarity" not in steps[0]


def test_action_packet_fallback_when_gemini_key_missing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    case = client.post("/api/cases/analyze", json={"text": "Breaking rumor spreading fast"}).json()
    resp = client.post(f"/api/cases/{case['case_id']}/action-packet", json={"audience": "public"})
    assert resp.status_code == 200
    packet = resp.json()
    assert packet["generated"] is False
    assert len(packet["sections"]) > 0
    assert any(s["heading"] == "Suggested countermeasures" for s in packet["sections"])


def test_action_packet_gemini_success(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")
    case = client.post("/api/cases/analyze", json={"text": "Phishing scam alert link"}).json()

    mock_response = MagicMock()
    mock_response.text = '''{
      "draft": "Public clarification: This content is unverified and flagged for suspected phishing.",
      "sections": [
        {
          "heading": "Platform Takedown Notice",
          "items": ["Requesting immediate review under phishing policy", "Domain identified in scam database"]
        },
        {
          "heading": "Counter-Narrative Post",
          "items": ["Official advisory: do not click suspicious links pretending to offer free rewards."]
        }
      ]
    }'''

    mock_model = MagicMock()
    mock_model.generate_content.return_value = mock_response

    with patch("google.generativeai.GenerativeModel", return_value=mock_model):
        resp = client.post(f"/api/cases/{case['case_id']}/action-packet", json={"audience": "moderators"})
        assert resp.status_code == 200
        packet = resp.json()
        assert packet["generated"] is True
        assert "AI-generated" in packet["label"]
        assert "phishing" in packet["draft"].lower()
        headings = [s["heading"] for s in packet["sections"]]
        assert "Platform Takedown Notice" in headings
        assert "Counter-Narrative Post" in headings


def test_action_packet_gemini_failure_falls_back(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")
    case = client.post("/api/cases/analyze", json={"text": "Another test rumor"}).json()

    with patch("google.generativeai.GenerativeModel", side_effect=RuntimeError("API quota exceeded")):
        resp = client.post(f"/api/cases/{case['case_id']}/action-packet", json={"audience": "moderators"})
        assert resp.status_code == 200
        packet = resp.json()
        # Graceful fallback to static template
        assert packet["generated"] is False
        assert len(packet["sections"]) > 0


def test_action_packet_for_an_unknown_case_id_is_not_found():
    import pytest
    from fastapi import HTTPException

    from backend.api.app.fusion import action_packet

    with pytest.raises(HTTPException) as caught:
        action_packet("no-such-case")
    assert caught.value.status_code == 404
