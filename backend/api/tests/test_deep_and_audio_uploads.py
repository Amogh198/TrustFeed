"""The dashboard can ask for deep checks, and audio uploads become cases. No model or network is used."""

import sys

import pytest
from fastapi.testclient import TestClient

from backend.api.app import main
from backend.api.app.main import MEDIA_UPLOAD_PATH, app
from backend.api.tests.test_wiring import png_bytes
from backend.media import analyze_media
from backend.media.tests.helpers import FakeClassifier
from backend.media.tests.test_audio_files import (
    FakeDetector,
    FakeTranscriber,
    write_wav,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def empty_case_store():
    main.CASES.clear()
    main.CASE_STORE.clear()
    yield
    main.CASES.clear()
    main.CASE_STORE.clear()


def test_deep_checks_run_only_when_asked(monkeypatch):
    asked = []

    def fake(path, **kwargs):
        asked.append(kwargs)
        return analyze_media(path, classifier=FakeClassifier(0.1))

    monkeypatch.setattr(main, "analyze_media", fake)
    for data in ({}, {"deep_check": "false"}, {"deep_check": "true"}):
        response = client.post(MEDIA_UPLOAD_PATH, files={"file": ("a.png", png_bytes(), "image/png")}, data=data)
        assert response.status_code == 200
    assert asked == [{}, {}, {"run_heavy": True}]


def test_audio_without_the_reader_installed_is_unavailable_not_corrupt(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "av", None)
    wav = write_wav(tmp_path / "voice.wav").read_bytes()
    response = client.post(MEDIA_UPLOAD_PATH, files={"file": ("voice.wav", wav, "audio/wav")})
    assert response.status_code == 200
    media = response.json()["modules"]["media"]
    assert media["status"] == "unavailable" and media["score"] is None
    assert any("PyAV" in line for line in media["limitations"])


def test_an_audio_upload_makes_a_case_with_speech_and_no_media_score(monkeypatch, tmp_path):
    pytest.importorskip("av")
    monkeypatch.setattr(
        main,
        "analyze_media",
        lambda path: analyze_media(path, transcriber=FakeTranscriber(), audio_detectors=[("fake/a", "1", FakeDetector(0.9))]),
    )
    wav = write_wav(tmp_path / "voice.wav").read_bytes()
    response = client.post(MEDIA_UPLOAD_PATH, files={"file": ("voice.wav", wav, "audio/wav")})
    assert response.status_code == 200
    body = response.json()
    assert body["modules"]["media"]["score"] is None
    assert any("Speech was read" in line for line in body["modules"]["media"]["evidence"])
    assert body["unified_risk"]["components"][0]["results_file"] is None
    checks = client.get(f"/api/cases/{body['case_id']}/explanation").json()["checks"]
    speech = next(check for check in checks if check["check_id"] == "media.speech")
    assert speech["artifacts"][0]["text"] == "Hello there."
    assert speech["artifacts"][0]["label"] == "Speech"
