"""A video's keyframes get the same checks and reasoning as a photo."""

from backend.media import analyze_media
from backend.media.metadata import read_video_tags
from backend.media.models import CheckStatus
from backend.media.tests.helpers import FakeClassifier, write_video

SCENES = [((0, 0, 255), 1.0), ((0, 255, 0), 1.0), ((255, 0, 0), 1.0)]


class Other(FakeClassifier):
    model_id = "other/detector"


def _panel(config):
    return Other(0.2)


def test_every_frame_gets_its_own_detector_scores_and_a_picture(tmp_path):
    video = write_video(tmp_path / "clip.mp4", SCENES)
    result = analyze_media(video, classifier=FakeClassifier(0.9), run_panel=True, panel_factory=_panel)
    frames = result.checks.keyframes.frames
    assert len(frames) >= 2
    for frame in frames:
        assert frame.detector_scores["test/fake-model"] == 0.9
        assert any(score == 0.2 for score in frame.detector_scores.values())
        assert frame.thumbnail and frame.thumbnail.startswith("data:image/jpeg;base64,")


def test_the_keyframe_check_explains_each_frame(tmp_path):
    video = write_video(tmp_path / "clip.mp4", SCENES)
    result = analyze_media(video, classifier=FakeClassifier(0.9), run_panel=True, panel_factory=_panel)
    check = next(item for item in result.to_checks() if item["check_id"] == "media.keyframes")
    assert len(check["artifacts"]) == len(result.checks.keyframes.frames)
    first = check["artifacts"][0]
    assert first["type"] == "frame" and first["label"].startswith("At ") and "90.00 out of 100" in first["text"]
    assert "same checks as a photo" in check["reasoning"]


def test_forensics_run_on_frames_and_say_they_were_measured_on_images(tmp_path):
    video = write_video(tmp_path / "clip.mp4", SCENES)
    forensics = analyze_media(video, classifier=FakeClassifier(0.9)).checks.forensics
    # The test clip is too small for these tests, which must say so instead of reading as clean.
    assert forensics.status in (CheckStatus.COMPLETE, CheckStatus.UNAVAILABLE)
    assert forensics.frame_timestamp_s is not None
    assert any("measured on images" in line for line in forensics.limitations)


def test_tags_are_read_when_the_library_is_there_and_never_stop_analysis(tmp_path):
    video = write_video(tmp_path / "clip.mp4", SCENES)
    tags = read_video_tags(video)
    if tags is not None:
        fields, named, notes = tags
        assert named is False and notes == [] and "comment" not in fields
    assert read_video_tags(tmp_path / "missing.mp4") is None
