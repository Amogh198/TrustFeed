import os

# Tests never download the public threat feeds.
os.environ["LINK_THREAT_FEEDS"] = "off"
"""Keep API tests the same on every machine, whatever models happen to be downloaded."""

import pytest

from backend.text import ner, verification


@pytest.fixture(autouse=True)
def no_models_or_outside_services(monkeypatch, tmp_path):
    # An empty cache means the real models report "not downloaded", and nothing loads them.
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty-model-cache"))
    monkeypatch.setattr(ner, "_default_runner", None)
    monkeypatch.setattr(verification, "_comparer", None)
    monkeypatch.setattr(verification, "default_providers", list)
