"""Faces, on-screen text, audio, speech and frame by frame scores, with stand-ins for every model."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.media import MediaConfig, analyze_media, audio, faces, frames, ocr
from backend.media import analyzer as analyzer_module
from backend.media.audio import (
    AUDIO_DETECTORS,
    SPEECH_MODEL,
    AudioTrack,
    choose_windows,
    detect_synthetic_speech,
    extract_audio,
    is_silent,
    transcribe_speech,
)
from backend.media.errors import ClassifierUnavailable
from backend.media.faces import FaceBox, analyze_faces, crop_face
from backend.media.frames import find_changes, find_sections, score_frames
from backend.media.models import CheckStatus, FrameScore, ModelBand
from backend.media.ocr import OcrUnavailable, clean_line, read_text
from backend.media.tests.helpers import FakeClassifier, write_video

TEST_PLAIN = Image.new("RGB", (256, 256), (120, 130, 140))


def tone(seconds: float = 3.0, level: float = 0.2) -> AudioTrack:
    times = np.arange(int(seconds * 16000), dtype=np.float32) / 16000
    return AudioTrack((np.sin(2 * np.pi * 220 * times) * level).astype(np.float32), seconds, False)


def video_with_audio(path: Path, seconds: float = 2.0, *, with_audio: bool = True) -> Path:
    import av

    with av.open(str(path), "w") as container:
        picture = container.add_stream("mpeg4", rate=10)
        picture.width, picture.height, picture.pix_fmt = 128, 128, "yuv420p"
        sound = container.add_stream("aac", rate=16000) if with_audio else None
        for index in range(int(seconds * 10)):
            pixels = np.full((128, 128, 3), index * 10 % 255, dtype=np.uint8)
            for packet in picture.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                container.mux(packet)
        for packet in picture.encode():
            container.mux(packet)
        if sound is not None:
            samples = (tone(seconds).samples * 32767).astype(np.int16).reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
            frame.sample_rate = 16000
            for packet in sound.encode(frame):
                container.mux(packet)
            for packet in sound.encode():
                container.mux(packet)
    return path


class FakeTranscriber:
    model_id, model_revision = SPEECH_MODEL

    def __init__(self, pieces=None, error=None):
        self.pieces = pieces if pieces is not None else [("  Hello\x00 there ", 0.0, 1.5), ("second", 1.5, None), ("  ", 2.0, 2.1)]
        self.error = error
        self.calls = 0

    def transcribe(self, samples, rate):
        self.calls += 1
        if self.error:
            raise self.error
        return self.pieces


class FakeAudioDetector:
    def __init__(self, score=0.7, error=None, wrong_length=False):
        self.score, self.error, self.wrong_length = score, error, wrong_length

    def score_windows(self, windows, rate):
        if self.error:
            raise self.error
        return [] if self.wrong_length else [self.score] * len(windows)


# Faces.


def test_faces_are_boxed_and_scored_one_at_a_time(monkeypatch):
    monkeypatch.setattr(faces, "detect_faces", lambda image: [FaceBox(10, 20, 100, 100), FaceBox(120, 20, 60, 60)])
    check = analyze_faces([(None, TEST_PLAIN)], FakeClassifier(0.9), MediaConfig())
    assert check.status is CheckStatus.COMPLETE
    assert [(f.x, f.y, f.width, f.height) for f in check.faces] == [(10, 20, 100, 100), (120, 20, 60, 60)]
    assert check.faces[0].scores[0].band is ModelBand.ELEVATED
    # A crop under the reliable size is never called elevated, however high its score.
    assert check.faces[1].scores[0].band is ModelBand.INCONCLUSIVE
    assert any("smaller than" in line for line in check.limitations)


def test_face_results_hold_only_boxes_and_scores_and_say_nobody_is_identified(monkeypatch):
    monkeypatch.setattr(faces, "detect_faces", lambda image: [FaceBox(10, 20, 100, 100)])
    check = analyze_faces([(None, TEST_PLAIN)], FakeClassifier(0.5), MediaConfig())
    assert set(check.faces[0].model_dump()) == {"x", "y", "width", "height", "timestamp_s", "scores"}
    assert "never identifies anyone" in " ".join(check.limitations)
    assert "face swaps has not been measured" in " ".join(check.limitations)


def test_no_faces_is_complete_and_scores_nothing(monkeypatch):
    monkeypatch.setattr(faces, "detect_faces", lambda image: [])
    classifier = FakeClassifier(0.5)
    check = analyze_faces([(None, TEST_PLAIN)], classifier, MediaConfig())
    assert check.status is CheckStatus.COMPLETE and check.faces == []


def test_faces_keep_a_timestamp_for_video(monkeypatch):
    monkeypatch.setattr(faces, "detect_faces", lambda image: [FaceBox(0, 0, 200, 200)])
    check = analyze_faces([(1.5, TEST_PLAIN)], FakeClassifier(0.5), MediaConfig())
    assert check.faces[0].timestamp_s == 1.5


def test_a_cap_stops_too_many_faces(monkeypatch):
    monkeypatch.setattr(faces, "detect_faces", lambda image: [FaceBox(0, 0, 200, 200)] * 5)
    check = analyze_faces([(None, TEST_PLAIN)], FakeClassifier(0.5), MediaConfig(max_faces=2))
    assert len(check.faces) == 2
    assert any("first 2 faces" in line for line in check.limitations)


def test_a_detector_failure_keeps_the_boxes(monkeypatch):
    class Broken(FakeClassifier):
        def predict(self, images):
            raise ClassifierUnavailable("no weights")

    monkeypatch.setattr(faces, "detect_faces", lambda image: [FaceBox(0, 0, 200, 200)])
    check = analyze_faces([(None, TEST_PLAIN)], Broken(0.5), MediaConfig())
    assert check.status is CheckStatus.COMPLETE
    assert check.faces[0].scores == []
    assert any("gave no result" in line for line in check.limitations)


def test_face_finding_failing_on_every_frame_is_unavailable(monkeypatch):
    def fail(image):
        raise RuntimeError("bad")

    monkeypatch.setattr(faces, "detect_faces", fail)
    assert analyze_faces([(None, TEST_PLAIN)], FakeClassifier(0.5), MediaConfig()).status is CheckStatus.UNAVAILABLE


def test_the_panel_scores_faces_when_asked(monkeypatch):
    monkeypatch.setattr(faces, "detect_faces", lambda image: [FaceBox(0, 0, 200, 200)])
    classifier = FakeClassifier(0.5)
    built = []

    def factory(config):
        built.append(config.model_id)
        return FakeClassifier(0.8)

    check = analyze_faces(
        [(None, TEST_PLAIN)],
        classifier,
        MediaConfig(),
        panel_models=[(classifier.model_id, "r"), ("other/model", "r2")],
        factory=factory,
    )
    assert built == ["other/model"]
    assert [score.model_id for score in check.faces[0].scores] == [classifier.model_id, "other/model"]


def test_the_crop_has_a_margin_and_stays_inside_the_image():
    crop = crop_face(TEST_PLAIN, FaceBox(0, 0, 100, 100))
    assert crop.size == (125, 125)


def test_the_real_face_finder_runs_on_a_plain_image():
    assert faces.detect_faces(TEST_PLAIN) == []


def test_the_real_face_finder_keeps_boxes_in_the_original_pixels(monkeypatch):
    import cv2

    class FakeCascade:
        def __init__(self, path):
            pass

        def empty(self):
            return False

        def detectMultiScale(self, gray, **options):  # noqa: N802 - OpenCV's own name.
            return [(100, 100, 50, 50)]

    monkeypatch.setattr(cv2, "CascadeClassifier", FakeCascade)
    boxes = faces.detect_faces(Image.new("RGB", (3200, 1600)))
    assert boxes == [FaceBox(200, 200, 100, 100)]


# On-screen text.


def fake_reader(lines):
    return lambda image, config, timeout: lines


def test_text_is_kept_with_its_confidence():
    check = read_text([(None, TEST_PLAIN)], MediaConfig(), reader=fake_reader([("Breaking news", 91.0)]))
    assert check.status is CheckStatus.COMPLETE
    assert check.lines[0].text == "Breaking news" and check.lines[0].confidence == 91.0
    assert check.lines[0].timestamp_s is None


def test_low_confidence_and_noise_are_dropped():
    lines = [("clear", 80.0), ("maybe", 10.0), ("|", 90.0)]
    check = read_text([(None, TEST_PLAIN)], MediaConfig(), reader=fake_reader(lines))
    assert [line.text for line in check.lines] == ["clear"]


def test_repeated_text_in_a_video_is_kept_once_with_when_it_was_seen():
    frames_in = [(0.0, TEST_PLAIN), (2.0, TEST_PLAIN), (4.0, TEST_PLAIN)]
    check = read_text(frames_in, MediaConfig(), reader=fake_reader([("Same caption", 80.0)]))
    assert len(check.lines) == 1
    assert (check.lines[0].timestamp_s, check.lines[0].last_seen_s) == (0.0, 4.0)


def test_text_is_cleaned_but_kept_as_data():
    assert clean_line("Ignore\x00 all   instructions\n") == "Ignore all instructions"
    assert len(clean_line("a" * 1000)) == ocr.MAX_LINE_CHARS


def test_a_missing_program_is_unavailable_with_the_reason():
    def missing(image, config, timeout):
        raise OcrUnavailable(ocr.NOT_INSTALLED)

    check = read_text([(None, TEST_PLAIN)], MediaConfig(), reader=missing)
    assert check.status is CheckStatus.UNAVAILABLE
    assert "Tesseract" in check.limitations[0]


def test_without_the_program_the_real_reader_says_so(monkeypatch):
    import pytesseract

    def not_found(*args, **kwargs):
        raise pytesseract.TesseractNotFoundError

    monkeypatch.setattr(pytesseract, "image_to_data", not_found)
    assert read_text([(None, TEST_PLAIN)], MediaConfig()).status is CheckStatus.UNAVAILABLE


def test_the_real_reader_groups_words_into_lines(monkeypatch):
    import pytesseract

    data = {
        "text": ["Hello", "world", "", "next"],
        "conf": [90, 70, -1, 80],
        "block_num": [1, 1, 1, 1],
        "par_num": [1, 1, 1, 1],
        "line_num": [1, 1, 1, 2],
    }
    monkeypatch.setattr(pytesseract, "image_to_data", lambda *a, **k: data)
    check = read_text([(None, TEST_PLAIN)], MediaConfig())
    assert [(line.text, line.confidence) for line in check.lines] == [("Hello world", 80.0), ("next", 80.0)]


def test_a_frame_that_fails_does_not_stop_the_rest_and_nothing_is_logged(caplog):
    calls = []

    def flaky(image, config, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("secret text here")
        return [("kept", 90.0)]

    with caplog.at_level(logging.WARNING):
        check = read_text([(0.0, TEST_PLAIN), (1.0, TEST_PLAIN)], MediaConfig(), reader=flaky)
    assert [line.text for line in check.lines] == ["kept"]
    assert "secret text" not in caplog.text


def test_ocr_stops_at_its_time_limit():
    check = read_text([(0.0, TEST_PLAIN)], MediaConfig(ocr_time_limit_s=0.0), reader=fake_reader([("x y", 90.0)]))
    assert check.status is CheckStatus.UNAVAILABLE
    assert "limit" in " ".join(check.limitations)


# Audio.


def test_audio_comes_out_as_16khz_mono(tmp_path):
    track = extract_audio(video_with_audio(tmp_path / "a.mp4"), MediaConfig())
    assert track.sample_rate == 16000
    assert track.samples.ndim == 1
    assert track.duration_s == pytest.approx(2.0, abs=0.3)
    assert not is_silent(track)


def test_a_video_with_no_audio_gives_none(tmp_path):
    assert extract_audio(video_with_audio(tmp_path / "a.mp4", with_audio=False), MediaConfig()) is None


def test_long_audio_is_cut_at_the_limit_and_says_so(tmp_path):
    track = extract_audio(video_with_audio(tmp_path / "a.mp4"), MediaConfig(max_audio_seconds=0.5))
    assert track.truncated
    assert track.samples.size == 8000


def test_a_broken_file_is_reported_not_raised_past_the_caller(tmp_path):
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42 not really a video")
    with pytest.raises(audio.AudioUnavailable):
        extract_audio(path, MediaConfig())


# Speech.


def test_speech_comes_back_with_times():
    check = transcribe_speech(tone(), MediaConfig(), FakeTranscriber())
    assert check.status is CheckStatus.COMPLETE
    assert [(s.text, s.start_s, s.end_s) for s in check.segments] == [("Hello there", 0.0, 1.5), ("second", 1.5, None)]
    assert check.model_revision == SPEECH_MODEL[1]


def test_no_audio_track_is_complete_and_says_so():
    check = transcribe_speech(None, MediaConfig(), FakeTranscriber())
    assert check.status is CheckStatus.COMPLETE and check.has_audio is False


def test_silence_never_reaches_the_model_because_it_can_invent_words():
    transcriber = FakeTranscriber()
    check = transcribe_speech(tone(level=0.0), MediaConfig(), transcriber)
    assert transcriber.calls == 0
    assert check.segments == []
    assert "silent" in " ".join(check.limitations)


def test_missing_weights_are_unavailable_with_the_reason():
    check = transcribe_speech(tone(), MediaConfig(), FakeTranscriber(error=ClassifierUnavailable("no weights")))
    assert check.status is CheckStatus.UNAVAILABLE and check.limitations == ["no weights"]


def test_a_speech_failure_says_nothing_about_the_content(caplog):
    with caplog.at_level(logging.WARNING):
        check = transcribe_speech(tone(), MediaConfig(), FakeTranscriber(error=RuntimeError("heard: secret")))
    assert check.status is CheckStatus.UNAVAILABLE
    assert "secret" not in caplog.text and "secret" not in check.model_dump_json()


def test_the_real_transcriber_refuses_to_download_during_analysis(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    transcriber = audio.WhisperTranscriber(MediaConfig())
    assert transcriber._allow_download is False


# Synthetic speech.


def test_both_named_models_are_pinned():
    assert [model for model, _ in AUDIO_DETECTORS] == [
        "MelodyMachine/Deepfake-audio-detection-V2",
        "motheecreator/Deepfake-audio-detection",
    ]
    assert all(len(revision) == 40 for _, revision in AUDIO_DETECTORS)


def test_each_model_reports_for_itself_and_the_measurement_is_stated():
    detectors = [("a/one", "r1", FakeAudioDetector(0.2)), ("b/two", "r2", FakeAudioDetector(0.9))]
    check = detect_synthetic_speech(tone(25), MediaConfig(), detectors)
    assert check.status is CheckStatus.COMPLETE
    assert [d.score_mean for d in check.detectors] == [0.2, 0.9]
    assert check.detectors[0].windows_scored == 2
    assert "no better than guessing" in " ".join(check.limitations)


def test_one_model_failing_leaves_the_other():
    detectors = [("a/one", "r1", FakeAudioDetector(error=ClassifierUnavailable("no"))), ("b/two", "r2", FakeAudioDetector())]
    check = detect_synthetic_speech(tone(), MediaConfig(), detectors)
    assert check.status is CheckStatus.COMPLETE
    assert check.detectors[0].status is CheckStatus.UNAVAILABLE and check.detectors[0].reason == "no"


def test_all_models_failing_is_unavailable():
    detectors = [("a/one", "r1", FakeAudioDetector(error=RuntimeError("x")))]
    assert detect_synthetic_speech(tone(), MediaConfig(), detectors).status is CheckStatus.UNAVAILABLE


def test_invalid_model_output_is_not_reported_as_a_score():
    detectors = [("a/one", "r1", FakeAudioDetector(wrong_length=True)), ("b/two", "r2", FakeAudioDetector(1.5))]
    check = detect_synthetic_speech(tone(), MediaConfig(), detectors)
    assert check.status is CheckStatus.UNAVAILABLE


def test_no_audio_is_not_applicable_and_silence_is_unavailable():
    assert detect_synthetic_speech(None, MediaConfig()).status is CheckStatus.NOT_APPLICABLE
    assert detect_synthetic_speech(tone(level=0.0), MediaConfig()).status is CheckStatus.UNAVAILABLE


def test_windows_are_spread_over_the_track_and_capped():
    assert len(choose_windows(tone(5))) == 1
    assert len(choose_windows(tone(35))) == 3
    assert len(choose_windows(tone(200))) == audio.MAX_WINDOWS
    assert choose_windows(tone(0.5)) == []


def test_a_model_past_the_time_limit_is_not_started():
    detectors = [("a/one", "r1", FakeAudioDetector())]
    check = detect_synthetic_speech(tone(), MediaConfig(audio_time_limit_s=0.0), detectors)
    assert check.status is CheckStatus.UNAVAILABLE
    assert "limit" in check.detectors[0].reason


# Frames.


def _scores(*values: float) -> list[FrameScore]:
    return [FrameScore(timestamp_s=float(i), score=value, scene_change=0.1) for i, value in enumerate(values)]


def test_sections_join_across_one_quiet_frame_and_split_across_two():
    sections = find_sections(_scores(0.9, 0.1, 0.8, 0.1, 0.1, 0.95, 0.1), 0.75)
    assert [(s.start_s, s.end_s, s.frames, s.strongest) for s in sections] == [(0.0, 2.0, 2, 0.9), (5.0, 5.0, 1, 0.95)]


def test_a_section_running_to_the_end_is_kept():
    assert find_sections(_scores(0.1, 0.9, 0.9), 0.75)[0].end_s == 2.0


def test_at_the_limit_counts_and_below_does_not():
    assert len(find_sections(_scores(0.75), 0.75)) == 1
    assert find_sections(_scores(0.74), 0.75) == []


def test_changes_list_the_biggest_jumps_both_ways():
    changes = find_changes(_scores(0.1, 0.9, 0.5, 0.6))
    assert [change.change for change in changes] == [0.8, -0.4]


def test_frames_are_scored_with_a_video_level_result(tmp_path):
    path = write_video(tmp_path / "a.mp4", [((10, 20, 30), 2.0), ((200, 100, 50), 2.0)])
    check = score_frames(path, FakeClassifier(0.9), MediaConfig())
    assert check.status is CheckStatus.COMPLETE
    assert len(check.frames) == 4
    assert check.frames_elevated == 4
    assert check.video_score == 0.9
    assert len(check.sections) == 1
    assert "not been measured" in " ".join(check.limitations)


def test_lip_sync_is_reported_as_not_available_with_why(tmp_path):
    path = write_video(tmp_path / "a.mp4", [((10, 20, 30), 1.0)])
    text = " ".join(score_frames(path, FakeClassifier(0.1), MediaConfig()).limitations)
    assert "Lip-sync was not checked" in text and "licence" in text


def test_a_long_video_is_sampled_across_its_length(tmp_path):
    path = write_video(tmp_path / "a.mp4", [((10, 20, 30), 6.0)])
    check = score_frames(path, FakeClassifier(0.1), MediaConfig(max_scored_frames=3))
    assert len(check.frames) == 3
    assert check.frames[-1].timestamp_s >= 3.0


def test_frames_stop_at_the_time_limit_and_keep_what_was_scored(tmp_path):
    path = write_video(tmp_path / "a.mp4", [((10, 20, 30), 6.0)])
    check = score_frames(path, FakeClassifier(0.1), MediaConfig(frames_time_limit_s=0.0, batch_size=2))
    assert check.status is CheckStatus.COMPLETE
    assert len(check.frames) == 2
    assert any("limit" in line for line in check.limitations)


def test_a_detector_failure_is_unavailable(tmp_path):
    class Broken(FakeClassifier):
        def predict(self, images):
            raise ClassifierUnavailable("no weights")

    path = write_video(tmp_path / "a.mp4", [((10, 20, 30), 1.0)])
    check = score_frames(path, Broken(0.1), MediaConfig())
    assert check.status is CheckStatus.UNAVAILABLE and check.limitations == ["no weights"]


def test_a_file_that_is_not_a_video_is_unavailable(tmp_path):
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"nothing here")
    assert score_frames(path, FakeClassifier(0.1), MediaConfig()).status is CheckStatus.UNAVAILABLE


# In the analysis.


def _heavy_video(tmp_path: Path):
    path = video_with_audio(tmp_path / "a.mp4")
    return analyze_media(
        path,
        classifier=FakeClassifier(0.9),
        config=MediaConfig(),
        run_heavy=True,
        transcriber=FakeTranscriber(),
        audio_detectors=[("a/one", "r1", FakeAudioDetector(0.7))],
    )


def test_a_video_reports_every_check_when_asked(tmp_path):
    entries = {check["check_id"]: check for check in _heavy_video(tmp_path).to_checks()}
    for check_id in ("media.faces", "media.ocr", "media.speech", "media.audio_synthetic", "media.frames"):
        assert check_id in entries
    assert entries["media.speech"]["status"] == "complete"
    assert entries["media.speech"]["result"] == "2 pieces of speech read"
    assert "measured once" in entries["media.audio_synthetic"]["result"]
    assert "accuracy unmeasured" in entries["media.frames"]["result"]


def test_every_new_check_has_string_artifacts_and_only_measured_ones_name_a_benchmark(tmp_path):
    result = _heavy_video(tmp_path)
    json.dumps(result.to_checks())
    for check in result.to_checks():
        assert set(check) >= {"check_id", "module", "label", "status", "result", "reasoning", "benchmark", "artifacts", "limitations"}
        if check["check_id"] in ("media.speech", "media.audio_synthetic", "media.frames", "media.faces", "media.ocr"):
            if check["check_id"] == "media.audio_synthetic":
                assert check["benchmark"] == {"results_file": "data/eval/audio_detectors_2026-11-06.json"}
            else:
                assert check["benchmark"] is None
            for artifact in check["artifacts"]:
                assert all(isinstance(value, str) for value in artifact.values())


def test_extracted_text_carries_speech_times_for_claim_checking(tmp_path):
    result = _heavy_video(tmp_path)
    assert result.extracted_text["speech"][0] == {"text": "Hello there", "start_s": 0.0, "end_s": 1.5}
    assert set(result.extracted_text) == {"ocr", "speech"}
    assert json.loads(result.model_dump_json())["extracted_text"]["speech"]


def test_extracted_text_carries_ocr_with_times(tmp_path, monkeypatch):
    def reading(frames_in, config):
        return read_text(frames_in, config, reader=fake_reader([("On screen", 90.0)]))

    monkeypatch.setattr(analyzer_module, "read_text", reading)
    path = write_video(tmp_path / "a.mp4", [((10, 20, 30), 1.0)])
    result = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig())
    assert result.extracted_text["ocr"][0]["text"] == "On screen"
    assert result.extracted_text["ocr"][0]["timestamp_s"] == 0.0


def test_an_image_has_ocr_with_no_time_and_no_speech(tmp_path, monkeypatch):
    def reading(frames_in, config):
        return read_text(frames_in, config, reader=fake_reader([("On screen", 90.0)]))

    monkeypatch.setattr(analyzer_module, "read_text", reading)
    path = tmp_path / "a.png"
    TEST_PLAIN.save(path)
    result = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig())
    assert result.extracted_text["ocr"][0]["timestamp_s"] is None
    assert result.extracted_text["speech"] == []


def test_a_rejected_file_has_empty_extracted_text(tmp_path):
    path = tmp_path / "bad.png"
    path.write_bytes(b"nope")
    result = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig())
    assert result.extracted_text == {"ocr": [], "speech": []}


def test_heavy_checks_stay_off_unless_asked_and_say_how_to_ask(tmp_path):
    path = video_with_audio(tmp_path / "a.mp4")
    transcriber = FakeTranscriber()
    result = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig(), transcriber=transcriber)
    assert transcriber.calls == 0
    assert result.checks.speech.status is CheckStatus.UNAVAILABLE
    assert "on request" in result.checks.speech.limitations[0]
    assert "Lip-sync" in " ".join(result.checks.frames.limitations)


def test_the_setting_turns_heavy_checks_on(tmp_path):
    path = video_with_audio(tmp_path / "a.mp4")
    transcriber = FakeTranscriber()
    analyze_media(
        path,
        classifier=FakeClassifier(0.1),
        config=MediaConfig(run_heavy_checks=True),
        transcriber=transcriber,
        audio_detectors=[("a/one", "r1", FakeAudioDetector())],
    )
    assert transcriber.calls == 1


def test_new_checks_never_change_the_score_or_assessment(tmp_path):
    path = video_with_audio(tmp_path / "a.mp4")
    plain = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig())
    heavy = analyze_media(
        path,
        classifier=FakeClassifier(0.1),
        config=MediaConfig(),
        run_heavy=True,
        transcriber=FakeTranscriber(),
        audio_detectors=[("a/one", "r1", FakeAudioDetector(0.99))],
    )
    assert (heavy.score, heavy.assessment, heavy.summary) == (plain.score, plain.assessment, plain.summary)


def test_without_pyav_the_speech_checks_are_unavailable_and_the_rest_carry_on(tmp_path, monkeypatch):
    def missing(path, config):
        raise audio.AudioUnavailable("Reading audio needs PyAV, which isn't installed.")

    monkeypatch.setattr(analyzer_module, "extract_audio", missing)
    path = write_video(tmp_path / "a.mp4", [((10, 20, 30), 1.0)])
    result = analyze_media(path, classifier=FakeClassifier(0.1), config=MediaConfig(), run_heavy=True)
    assert result.checks.speech.status is CheckStatus.UNAVAILABLE
    assert result.checks.audio_synthetic.status is CheckStatus.UNAVAILABLE
    assert result.checks.frames.status is CheckStatus.COMPLETE
    assert result.status is CheckStatus.COMPLETE


def test_stuck_speech_stops_at_its_limit(tmp_path):
    import time

    class Stuck(FakeTranscriber):
        def transcribe(self, samples, rate):
            time.sleep(1.0)
            return []

    path = video_with_audio(tmp_path / "a.mp4")
    result = analyze_media(
        path,
        classifier=FakeClassifier(0.1),
        config=MediaConfig(speech_time_limit_s=0.05),
        run_heavy=True,
        transcriber=Stuck(),
        audio_detectors=[("a/one", "r1", FakeAudioDetector())],
    )
    assert result.checks.speech.status is CheckStatus.UNAVAILABLE
    assert "didn't finish" in result.checks.speech.limitations[0]


def test_the_explanation_handles_a_check_that_did_not_run():
    from backend.media.explain import _audio_synthetic, _faces, _frames, _ocr, _speech
    from backend.media.models import AudioSyntheticCheck, FacesCheck, FramesCheck, OcrCheck, SpeechCheck

    for build, model in (
        (_faces, FacesCheck),
        (_ocr, OcrCheck),
        (_speech, SpeechCheck),
        (_audio_synthetic, AudioSyntheticCheck),
        (_frames, FramesCheck),
    ):
        entry = build(model(status=CheckStatus.UNAVAILABLE, limitations=["why"]))
        assert entry["result"] == "Not run" and entry["limitations"] == ["why"]


def test_frames_module_is_importable_on_its_own():
    assert frames.MAX_CHANGES == 5
