from __future__ import annotations

from pathlib import Path

import pytest

from backend.media.tests.helpers import patterned_image, write_video


@pytest.fixture
def image_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.png"
    patterned_image().save(path)
    return path


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    red, blue = (0, 0, 255), (255, 0, 0)
    return write_video(tmp_path / "sample.mp4", [(red, 2.0), (blue, 2.0)])
