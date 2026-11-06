"""Keep API tests the same on every machine, whatever models happen to be downloaded."""

import os
import tempfile
from pathlib import Path

import pytest

# Tests never download the public threat feeds or run the trust models.
os.environ["LINK_THREAT_FEEDS"] = "off"
os.environ["TRUST_MODELS"] = "off"
os.environ["MEDIA_PANEL"] = "off"
# Tests clear the case store, so they must never share the database the running app uses.
os.environ["CASE_STORE_PATH"] = str(Path(tempfile.mkdtemp(prefix="trustfeed-tests-")) / "cases.db")

from backend.text import ner, verification


@pytest.fixture(autouse=True)
def no_models_or_outside_services(monkeypatch, tmp_path):
    # An empty cache means the real models report "not downloaded", and nothing loads them.
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty-model-cache"))
    monkeypatch.setattr(ner, "_default_runner", None)
    monkeypatch.setattr(verification, "_comparer", None)
    monkeypatch.setattr(verification, "default_providers", list)
