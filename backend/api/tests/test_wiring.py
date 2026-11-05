"""The API's connections to the media and network lanes."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.app import main
from backend.api.app.fusion import combine_risks
from backend.api.app.main import MEDIA_UPLOAD_PATH, app
from backend.api.app.models import RiskLevel
from backend.media import MediaConfig, analyze_media
from backend.media.errors import ClassifierUnavailable
from backend.media.tests.helpers import FakeClassifier, patterned_image, write_video

client = TestClient(app)
RED, BLUE = (0, 0, 255), (255, 0, 0)
SCAM_TEXT = "Urgent! Forward this now to claim your prize!!!"


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    patterned_image().save(buffer, format="PNG")
    return buffer.getvalue()


def upload(content: bytes, name: str = "photo.png", **fields):
    return client.post(MEDIA_UPLOAD_PATH, files={"file": (name, content)}, data=fields)


@pytest.fixture
def analyzed_paths(monkeypatch):
    """Use a fake model and record the path the route hands to the media lane."""
    paths: list[Path] = []

    def use(score=0.5, error=None, config=None):
        def fake(path):
            paths.append(Path(path))
            assert paths[-1].exists()
            classifier = FakeClassifier(score, error=error)
            return analyze_media(path, classifier=classifier, config=config or MediaConfig())

        monkeypatch.setattr(main, "analyze_media", fake)
        return paths

    return use


# Network


def test_demo_network_is_served_and_labelled_synthetic():
    response = client.get("/api/network/demo-001")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"nodes", "edges", "timeline"}
    assert body["nodes"] and body["edges"] and body["timeline"]
    assert all(node["synthetic"] for node in body["nodes"])


def test_demo_case_reports_network_only_and_says_it_is_synthetic():
    response = client.get("/api/cases/demo-001")
    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "demo-001"
    assert body["overall_risk"] == "critical"
    assert "Synthetic" in body["summary"]
    assert body["modules"]["network"]["status"] == "complete"
    assert "SYNTHETIC" in body["modules"]["network"]["evidence"][0]
    for name in ("text", "url", "media"):
        assert body["modules"][name]["status"] == "not_applicable"


def test_demo_case_has_an_action_packet():
    response = client.post("/api/cases/demo-001/action-packet", json={})
    assert response.status_code == 200
    assert response.json()["generated"] is False
    assert response.json()["evidence_references"]


def test_submitted_case_never_receives_the_demo_network():
    case = client.post("/api/cases/analyze", json={"text": SCAM_TEXT}).json()
    assert case["modules"]["network"]["status"] == "unavailable"
    assert case["modules"]["network"]["score"] is None
    assert client.get(f"/api/network/{case['case_id']}").json() == {"nodes": [], "edges": [], "timeline": []}


def test_unknown_case_is_still_not_found():
    assert client.get("/api/network/unknown").status_code == 404
    assert client.get("/api/cases/unknown").status_code == 404
    assert client.post("/api/cases/unknown/action-packet", json={}).status_code == 404


def test_json_route_reports_media_as_not_submitted():
    body = client.post("/api/cases/analyze", json={"text": "A community meeting."}).json()
    assert body["modules"]["media"]["status"] == "not_applicable"
    assert body["modules"]["media"]["score"] is None


# Media upload


@pytest.mark.parametrize(
    ("score", "risk", "human_review"),
    [(0.9, "high", True), (0.1, "inconclusive", False), (0.5, "inconclusive", False)],
)
def test_image_upload_uses_the_media_assessment(analyzed_paths, score, risk, human_review):
    analyzed_paths(score)
    response = upload(png_bytes())
    assert response.status_code == 200
    body = response.json()
    media = body["modules"]["media"]
    assert media["status"] == "complete"
    assert media["score"] == score
    assert media["confidence"] is None
    assert media["limitations"]
    assert body["overall_risk"] == risk
    assert any("person review" in action for action in body["recommended_actions"]) is human_review
    assert "not a factual verdict" in body["summary"] or risk == "inconclusive"
    assert client.get(f"/api/cases/{body['case_id']}").json() == body


def test_low_media_signal_is_not_presented_as_authentic(analyzed_paths):
    analyzed_paths(0.05)
    body = upload(png_bytes()).json()
    assert any("does not establish that the media is authentic" in line for line in body["uncertainties"])


def test_upload_is_deleted_and_the_client_name_is_not_used(analyzed_paths):
    paths = analyzed_paths(0.5)
    response = upload(png_bytes(), name="..\\..\\private-name.png")
    assert response.status_code == 200
    assert len(paths) == 1
    assert not paths[0].exists()
    assert "private-name" not in str(paths[0])
    assert str(paths[0]) not in response.text
    assert "private-name" not in response.text


def test_upload_is_deleted_when_analysis_crashes(monkeypatch):
    paths = []

    def crash(path):
        paths.append(Path(path))
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "analyze_media", crash)
    with TestClient(app, raise_server_exceptions=False) as local:
        response = local.post(MEDIA_UPLOAD_PATH, files={"file": ("a.png", png_bytes())})
    assert response.status_code == 500
    assert "boom" not in response.text
    assert not paths[0].exists()


def test_video_upload_reports_keyframes(analyzed_paths, tmp_path):
    analyzed_paths(0.9)
    video = write_video(tmp_path / "clip.mp4", [(RED, 2.0), (BLUE, 2.0)])
    response = upload(video.read_bytes(), name="clip.mp4")
    assert response.status_code == 200
    body = response.json()
    assert any("2 keyframes" in line for line in body["modules"]["media"]["evidence"])
    assert body["overall_risk"] == "high"


def test_video_with_disagreeing_frames_does_not_become_high_risk(analyzed_paths, tmp_path):
    analyzed_paths([0.05, 0.95])
    video = write_video(tmp_path / "clip.mp4", [(RED, 2.0), (BLUE, 2.0)])
    body = upload(video.read_bytes(), name="clip.mp4").json()
    assert body["modules"]["media"]["score"] == 0.95
    assert body["overall_risk"] == "inconclusive"


def test_unavailable_model_is_reported_without_a_score(analyzed_paths):
    analyzed_paths(error=ClassifierUnavailable("no weights"))
    response = upload(png_bytes())
    assert response.status_code == 200
    body = response.json()
    assert body["modules"]["media"]["status"] == "unavailable"
    assert body["modules"]["media"]["score"] is None
    assert "no weights" in " ".join(body["modules"]["media"]["limitations"])
    assert body["overall_risk"] == "inconclusive"


def test_text_and_url_are_fused_with_media(analyzed_paths):
    analyzed_paths(0.5)
    body = upload(png_bytes(), text=SCAM_TEXT, url="http://example.zip/login").json()
    assert body["modules"]["text"]["status"] == "complete"
    assert body["modules"]["url"]["status"] == "complete"
    assert body["modules"]["media"]["status"] == "complete"
    assert body["overall_risk"] == "high"


def test_quiet_text_does_not_hide_inconclusive_media(analyzed_paths):
    analyzed_paths(0.5)
    body = upload(png_bytes(), text="A community meeting will happen on Friday.").json()
    assert body["modules"]["text"]["score"] == 0
    assert body["overall_risk"] == "inconclusive"


def test_blank_form_fields_count_as_not_submitted(analyzed_paths):
    analyzed_paths(0.5)
    response = upload(png_bytes(), text="   ", url="")
    assert response.status_code == 200
    assert response.json()["modules"]["text"]["status"] == "not_applicable"
    assert response.json()["modules"]["url"]["status"] == "not_applicable"


# Rejected uploads


@pytest.mark.parametrize(
    ("content", "status", "code"),
    [
        (b"", 422, "empty_file"),
        (b"this is plain text, not media", 415, "unsupported_type"),
        (b"\x89PNG\r\n\x1a\nbroken", 422, "corrupt_media"),
    ],
)
def test_bad_files_are_rejected_without_creating_a_case(analyzed_paths, content, status, code):
    analyzed_paths(0.9)
    before = len(main.CASES)
    response = upload(content)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["message"]
    assert len(main.CASES) == before


def test_file_over_the_media_limit_is_rejected(analyzed_paths):
    analyzed_paths(0.9, config=MediaConfig(max_image_bytes=10))
    response = upload(png_bytes())
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "too_large"


def test_oversized_body_is_refused_before_parsing(analyzed_paths, monkeypatch):
    paths = analyzed_paths(0.9)
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)
    response = client.post(
        MEDIA_UPLOAD_PATH,
        files={"file": ("a.png", png_bytes())},
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "too_large"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert paths == []


def test_body_without_a_declared_length_is_refused(analyzed_paths):
    paths = analyzed_paths(0.9)

    def chunks():
        yield b"data"

    response = client.post(MEDIA_UPLOAD_PATH, content=chunks(), headers={"Content-Type": "multipart/form-data"})
    assert response.status_code == 411
    assert paths == []


def test_size_limit_does_not_touch_other_routes(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1)
    assert client.post("/api/cases/analyze", json={"text": SCAM_TEXT}).status_code == 200


def test_missing_file_and_bad_fields_are_validation_errors(analyzed_paths):
    paths = analyzed_paths(0.9)
    assert client.post(MEDIA_UPLOAD_PATH, data={"text": "no file"}).status_code == 422
    assert upload(png_bytes(), url="not a url").status_code == 422
    assert upload(png_bytes(), text="x" * 20_001).status_code == 422
    assert paths == []


# Fusion


@pytest.mark.parametrize(
    ("levels", "expected"),
    [
        ([], RiskLevel.INCONCLUSIVE),
        ([RiskLevel.INCONCLUSIVE], RiskLevel.INCONCLUSIVE),
        ([RiskLevel.LOW], RiskLevel.LOW),
        ([RiskLevel.LOW, RiskLevel.INCONCLUSIVE], RiskLevel.INCONCLUSIVE),
        ([RiskLevel.MODERATE, RiskLevel.INCONCLUSIVE], RiskLevel.MODERATE),
        ([RiskLevel.LOW, RiskLevel.HIGH], RiskLevel.HIGH),
        ([RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.LOW], RiskLevel.CRITICAL),
    ],
)
def test_combine_risks(levels, expected):
    assert combine_risks(levels) is expected
