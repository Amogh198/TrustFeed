from __future__ import annotations

import sys

from backend.media import MediaConfig, analyze_media
from backend.media.errors import ClassifierUnavailable
from backend.media.models import Assessment, CheckStatus, MediaType, ModelBand
from backend.media.phash import JsonHashIndex, ReferenceEntry, compute_phash
from backend.media.tests.helpers import FakeClassifier, patterned_image, write_video

RED, GREEN, BLUE = (0, 0, 255), (0, 255, 0), (255, 0, 0)


def test_keyframes_follow_scene_changes(video_file):
    classifier = FakeClassifier(0.5)
    result = analyze_media(video_file, classifier=classifier, config=MediaConfig())

    assert result.media_type is MediaType.VIDEO
    frames = result.checks.keyframes.frames
    assert [frame.timestamp_s for frame in frames] == [0.0, 2.0]
    assert classifier.seen == 2
    assert result.checks.metadata.duration_s == 4.0
    assert result.checks.metadata.width == 160
    assert all(frame.model_score == 0.5 and frame.phash for frame in frames)


def test_static_video_is_still_sampled_periodically(tmp_path):
    path = write_video(tmp_path / "static.mp4", [(RED, 25.0)], fps=4)
    result = analyze_media(path, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert [frame.timestamp_s for frame in result.checks.keyframes.frames] == [0.0, 10.0, 20.0]


def test_keyframe_cap_keeps_first_frame_and_reports_the_limit(tmp_path):
    scenes = [(RED if i % 2 else BLUE, 1.5) for i in range(12)]
    path = write_video(tmp_path / "cuts.mp4", scenes)
    result = analyze_media(path, classifier=FakeClassifier(0.5), config=MediaConfig(max_keyframes=3))
    frames = result.checks.keyframes.frames
    assert len(frames) == 3
    assert frames[0].timestamp_s == 0.0
    assert [f.timestamp_s for f in frames] == sorted(f.timestamp_s for f in frames)
    assert any("capped at 3" in line for line in result.limitations)


def test_analysis_time_limit_is_reported(tmp_path):
    path = write_video(tmp_path / "long.mp4", [(RED, 4.0)])
    result = analyze_media(path, classifier=FakeClassifier(0.5), config=MediaConfig(max_video_seconds=1))
    assert any("first 1 seconds" in line for line in result.limitations)


def test_video_score_uses_strongest_frames(tmp_path):
    scenes = [(RED, 2.0), (BLUE, 2.0), (GREEN, 2.0)]
    path = write_video(tmp_path / "three.mp4", scenes)
    result = analyze_media(path, classifier=FakeClassifier([0.8, 0.9, 0.85]), config=MediaConfig())
    assert result.score == 0.9
    assert result.checks.classifier.score_min == 0.8
    assert result.checks.classifier.band is ModelBand.ELEVATED
    assert any("0.0s, 2.0s, 4.0s" in line for line in result.evidence)


def test_disagreeing_frames_are_inconclusive(video_file):
    result = analyze_media(video_file, classifier=FakeClassifier([0.05, 0.95]), config=MediaConfig())
    assert result.checks.classifier.band is ModelBand.INCONCLUSIVE
    assert result.assessment is Assessment.INCONCLUSIVE
    assert any("disagree" in line for line in result.limitations)
    assert any("2.0s" in line for line in result.evidence)


def test_classifier_unavailable_keeps_keyframes(video_file):
    classifier = FakeClassifier(error=ClassifierUnavailable("no weights"))
    result = analyze_media(video_file, classifier=classifier, config=MediaConfig())
    assert result.status is CheckStatus.UNAVAILABLE
    assert result.score is None
    assert result.checks.keyframes.status is CheckStatus.COMPLETE
    assert all(frame.model_score is None for frame in result.checks.keyframes.frames)


def test_video_keyframe_matches_reference(video_file):
    from backend.media.keyframes import extract_keyframes

    _, frames, _ = extract_keyframes(video_file, MediaConfig())
    reference = compute_phash(frames[1].image)
    index = JsonHashIndex([ReferenceEntry(phash=reference, label="Known clip")])
    result = analyze_media(video_file, classifier=FakeClassifier(0.5), hash_index=index, config=MediaConfig())
    assert result.checks.phash.matches[0].label == "Known clip"
    assert result.checks.phash.matches[0].timestamp_s is not None
    assert result.assessment is Assessment.SIGNALS_PRESENT


def test_garbage_with_video_header_is_corrupt(tmp_path):
    path = tmp_path / "broken.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00garbage" * 200)
    result = analyze_media(path, classifier=FakeClassifier(), config=MediaConfig())
    assert result.failure_code == "corrupt_media"
    assert result.media_type is MediaType.VIDEO
    assert result.score is None


def test_truncated_video_is_reported_not_raised(video_file, tmp_path):
    data = video_file.read_bytes()
    path = tmp_path / "cut.mp4"
    path.write_bytes(data[: len(data) // 2])
    result = analyze_media(path, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert result.failure_code == "corrupt_media" or result.checks.keyframes.status is CheckStatus.COMPLETE


def test_heic_is_not_treated_as_video(tmp_path):
    path = tmp_path / "photo.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64)
    assert analyze_media(path, classifier=FakeClassifier(), config=MediaConfig()).failure_code == "unsupported_type"


def test_video_size_limit(video_file):
    result = analyze_media(video_file, classifier=FakeClassifier(), config=MediaConfig(max_video_bytes=10))
    assert result.failure_code == "too_large"


def test_missing_opencv_is_reported_and_images_still_work(video_file, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", None)
    result = analyze_media(video_file, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert result.failure_code == "dependency_missing"

    image_path = tmp_path / "still.png"
    patterned_image().save(image_path)
    image_result = analyze_media(image_path, classifier=FakeClassifier(0.5), config=MediaConfig())
    assert image_result.status is CheckStatus.COMPLETE
