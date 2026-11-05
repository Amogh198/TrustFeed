"""Network-free contract checks for the recorded case explanation."""

import pytest
from fastapi.testclient import TestClient

from backend.api.app import main
from backend.api.app.main import MEDIA_UPLOAD_PATH, app
from backend.api.tests.test_wiring import png_bytes
from backend.media import analyze_media
from backend.media.tests.helpers import FakeClassifier
from backend.provenance import ProvenanceReport, Status
from backend.provenance.models import Appearance, MatchType

client = TestClient(app)


@pytest.fixture(autouse=True)
def empty_case_store():
    main.CASES.clear()
    main.CASE_STORE.clear()
    yield
    main.CASES.clear()
    main.CASE_STORE.clear()


def test_demo_explanation_includes_recorded_network_and_provenance_checks():
    response = client.get("/api/cases/demo-001/explanation")

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "demo-001"
    checks = {item["check_id"]: item for item in body["checks"]}
    assert checks["network-trace"]["result"] == "complete"
    assert checks["provenance-search"]["result"] == "complete"
    assert all(item["benchmark"] is None for item in body["checks"])
    assert "synthetic" in " ".join(body["uncertainties"]).lower()


def test_upload_explanation_merges_media_provenance_and_network_checks(monkeypatch):
    monkeypatch.setattr(
        main,
        "analyze_media",
        lambda path: analyze_media(path, classifier=FakeClassifier(0.1)),
    )
    monkeypatch.setattr(
        main,
        "investigate_provenance",
        lambda path, *, search_web: ProvenanceReport(
            status=Status.COMPLETE,
            appearances=[
                Appearance(
                    id="web-1",
                    page_url="https://example.org/appearance",
                    domain="example.org",
                    match_type=MatchType.EXACT,
                    provider="fixture",
                )
            ],
        ),
    )
    monkeypatch.setattr(
        main,
        "trace_case",
        lambda *args, **kwargs: {
            "status": "complete",
            "score": None,
            "confidence": None,
            "evidence": ["Fixture trace found one matching public post."],
            "limitations": ["Fixture trace limitation."],
        },
    )
    monkeypatch.setattr(
        main,
        "get_network_payload",
        lambda case_id: {"nodes": [], "edges": [], "timeline": []},
    )
    monkeypatch.setattr(
        main,
        "get_network_coverage",
        lambda case_id: {
            "platforms": [{"label": "Fixture platform", "status": "searched"}],
            "spread": [{"platform": "fixture", "permalink": "https://example.org/post"}],
        },
    )

    created = client.post(
        MEDIA_UPLOAD_PATH,
        files={"file": ("sample.png", png_bytes())},
        data={"text": "Urgent! Act now.", "search_web": "true"},
    )
    assert created.status_code == 200

    response = client.get(f"/api/cases/{created.json()['case_id']}/explanation")
    assert response.status_code == 200
    checks = {item["check_id"]: item for item in response.json()["checks"]}
    assert {"media-classifier", "media-metadata", "media-phash", "media-keyframes"} <= set(checks)
    assert checks["provenance-search"]["artifacts"][0]["url"] == "https://example.org/appearance"
    assert checks["network-trace"]["artifacts"][0]["url"] == "https://example.org/post"
    assert checks["network-trace"]["result"] == "complete"
