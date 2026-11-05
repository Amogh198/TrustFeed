"""Keep API tests the same on every machine, whatever models happen to be downloaded."""

import pytest

from backend.text import ner


@pytest.fixture(autouse=True)
def no_downloaded_models(monkeypatch, tmp_path):
    # An empty cache means the real model reports "not downloaded", and nothing loads it.
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty-model-cache"))
    monkeypatch.setattr(ner, "_default_runner", None)
