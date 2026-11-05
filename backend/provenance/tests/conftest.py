from __future__ import annotations

import socket

import pytest

from backend.media.tests.helpers import patterned_image


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real connection attempt fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("A test tried to use the network.")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in (
        "GOOGLE_VISION_API_KEY",
        "TINEYE_API_KEY",
        "SERPAPI_API_KEY",
        "PROVENANCE_REPLAY_PATH",
        "MEDIA_PHASH_INDEX",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def image_file(tmp_path):
    path = tmp_path / "upload.jpg"
    patterned_image(seed=1).save(path, format="JPEG", quality=95)
    return path
