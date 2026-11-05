from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.media import MediaConfig, analyze_media
from backend.media.__main__ import main
from backend.media.config import DEFAULT_MODEL_ID, DEFAULT_MODEL_REVISION
from backend.media.errors import ClassifierUnavailable
from backend.media.tests.helpers import FakeClassifier, patterned_image

MODULE_KEYS = {"status", "score", "confidence", "evidence", "limitations"}
REPO_ROOT = Path(__file__).resolve().parents[3]


def _scenarios(image_file: Path, tmp_path: Path):
    missing = tmp_path / "missing.png"
    return [
        analyze_media(image_file, classifier=FakeClassifier(0.9), config=MediaConfig()),
        analyze_media(image_file, classifier=FakeClassifier(error=ClassifierUnavailable("x")), config=MediaConfig()),
        analyze_media(missing, classifier=FakeClassifier(), config=MediaConfig()),
    ]


def test_module_result_shape_and_rules(image_file, tmp_path):
    for result in _scenarios(image_file, tmp_path):
        payload = result.to_module_result()
        assert set(payload) == MODULE_KEYS
        assert payload["status"] in {"complete", "unavailable", "not_applicable"}
        assert all(isinstance(line, str) for line in payload["evidence"] + payload["limitations"])
        assert payload["confidence"] is None
        if payload["status"] == "unavailable":
            assert payload["score"] is None
            assert payload["limitations"]
        json.dumps(payload)


def test_module_result_validates_against_api_lane_model(image_file, tmp_path):
    """Skipped until the API lane's models are importable."""
    models = pytest.importorskip("backend.api.app.models")
    for result in _scenarios(image_file, tmp_path):
        models.ModuleResult.model_validate(result.to_module_result())


def test_full_result_is_json_serializable(image_file):
    result = analyze_media(image_file, classifier=FakeClassifier(0.5), config=MediaConfig())
    decoded = json.loads(result.model_dump_json())
    assert decoded["schema_version"] == "media-1"
    assert set(decoded["checks"]) == {"metadata", "classifier", "phash", "keyframes", "fingerprint"}


def test_importing_the_package_does_not_load_heavy_libraries():
    code = (
        "import sys, backend.media, backend.media.__main__;"
        "print([name for name in ('torch', 'transformers', 'cv2') if name in sys.modules])"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=REPO_ROOT)
    assert output.stdout.strip() == "[]"


def test_env_config(monkeypatch, tmp_path):
    for name in (
        "MEDIA_MODEL_ID",
        "MEDIA_MODEL_REVISION",
        "MEDIA_PHASH_INDEX",
        "MEDIA_ALLOW_MODEL_DOWNLOAD",
        "MEDIA_DEVICE",
    ):
        monkeypatch.delenv(name, raising=False)
    config = MediaConfig.from_env()
    assert config.model_id == DEFAULT_MODEL_ID
    assert config.model_revision == DEFAULT_MODEL_REVISION
    assert config.allow_model_download is False

    monkeypatch.setenv("MEDIA_MODEL_ID", "other/model")
    monkeypatch.setenv("MEDIA_ALLOW_MODEL_DOWNLOAD", "true")
    monkeypatch.setenv("MEDIA_PHASH_INDEX", str(tmp_path / "index.json"))
    config = MediaConfig.from_env()
    assert config.model_revision is None
    assert config.allow_model_download is True
    assert config.phash_index_path == tmp_path / "index.json"


def test_cli_index_add_then_analyze(tmp_path, capsys, monkeypatch):
    # A model that cannot exist keeps this test independent of local weights.
    monkeypatch.setenv("MEDIA_MODEL_ID", "trustfeed-tests/does-not-exist")
    image = tmp_path / "reference.png"
    patterned_image(seed=3).save(image)
    index = tmp_path / "index.json"

    assert main(["index-add", str(image), "--index", str(index), "--label", "Reference", "--first-seen", "2019"]) == 0
    capsys.readouterr()

    assert main(["analyze", str(image), "--index", str(index)]) == 0
    full = json.loads(capsys.readouterr().out)
    assert full["checks"]["phash"]["matches"][0]["label"] == "Reference"

    assert main(["analyze", str(image), "--index", str(index), "--module-only"]) == 0
    assert set(json.loads(capsys.readouterr().out)) == MODULE_KEYS


def test_cli_invalid_input_exit_code(tmp_path, capsys):
    assert main(["analyze", str(tmp_path / "missing.jpg")]) == 2
    assert json.loads(capsys.readouterr().out)["failure_code"] == "not_found"


def test_cli_index_add_rejects_bad_image(tmp_path, capsys):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    assert main(["index-add", str(bad), "--index", str(tmp_path / "i.json"), "--label", "x"]) == 2
    assert "error:" in capsys.readouterr().err
