"""T3 case history, replay and action-packet behaviour."""

import pytest
from fastapi.testclient import TestClient

from backend.api.app import main
from backend.api.app.main import app
from backend.text.analysis import extract_claims

client = TestClient(app)


@pytest.fixture(autouse=True)
def empty_case_store():
    main.CASES.clear()
    main.CASE_STORE.clear()
    yield
    main.CASES.clear()
    main.CASE_STORE.clear()


def test_claim_atomization_returns_sentence_like_unverified_units():
    assert extract_claims("First statement. Second statement?\nThird statement!") == [
        "First statement.",
        "Second statement?",
        "Third statement!",
    ]

    response = client.post(
        "/api/cases/analyze",
        json={"text": "The water is unsafe. Officials hid the report."},
    )
    claims = response.json()["claims"]
    assert [claim["text"] for claim in claims] == [
        "The water is unsafe.",
        "Officials hid the report.",
    ]
    assert {claim["verdict"] for claim in claims} == {"unverified"}
    assert all("No external evidence" in claim["rationale"] for claim in claims)


def test_case_history_persists_when_the_in_memory_cache_is_cleared():
    created = client.post("/api/cases/analyze", json={"text": "Urgent: act now."}).json()
    main.CASES.clear()

    response = client.get(f"/api/cases/{created['case_id']}")
    assert response.status_code == 200
    assert response.json() == created

    history = client.get("/api/cases").json()
    assert history["total"] == 1
    assert history["cases"][0]["case_id"] == created["case_id"]


def test_history_filters_by_risk_and_export_returns_the_full_case():
    low = client.post("/api/cases/analyze", json={"text": "A community meeting is on Friday."}).json()
    high = client.post(
        "/api/cases/analyze",
        json={"text": "Urgent! Act now to claim your prize."},
    ).json()

    filtered = client.get("/api/cases?risk_level=high").json()
    assert filtered["total"] == 1
    assert filtered["cases"][0]["case_id"] == high["case_id"]
    assert client.get(f"/api/cases/{low['case_id']}/export").json() == low


def test_offline_replay_is_listed_labelled_and_saved_as_a_case():
    scenarios = client.get("/api/replay/scenarios")
    assert scenarios.status_code == 200
    scenario = scenarios.json()["scenarios"][0]
    assert scenario["id"] == "offline-claim-url-demo"
    assert scenario["label"].startswith("SYNTHETIC OFFLINE REPLAY")

    started = client.post(f"/api/replay/{scenario['id']}/start")
    assert started.status_code == 200
    body = started.json()
    assert body["is_replay"] is True
    assert body["replay_label"] == scenario["label"]
    assert body["claims"]
    assert client.get(f"/api/cases/{body['case_id']}").json() == body


def test_unknown_replay_scenario_is_not_found():
    assert client.post("/api/replay/unknown/start").status_code == 404


def test_action_packet_uses_case_evidence_claims_and_uncertainties():
    case = client.post(
        "/api/cases/analyze",
        json={"text": "Urgent! Act now to claim your prize."},
    ).json()

    packet = client.post(f"/api/cases/{case['case_id']}/action-packet", json={"audience": "reviewers"})
    assert packet.status_code == 200
    body = packet.json()
    assert body["generated"] is False
    assert "no generative model" in body["label"].lower()
    headings = [section["heading"] for section in body["sections"]]
    assert headings == [
        "Assessment",
        "Evidence observed",
        "Claim status",
        "Uncertainties",
        "Recommended next actions",
    ]
    assert body["evidence_references"]
    assert "reviewers" in body["draft"]
