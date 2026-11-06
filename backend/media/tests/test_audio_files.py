"""Audio files are read and checked for speech, and get no image score."""

import wave

import numpy as np
import pytest

from backend.media import analyze_media
from backend.media.metadata import sniff_media_type
from backend.media.models import Assessment, CheckStatus, MediaType


class FakeTranscriber:
    model_id = "fake/speech"
    model_revision = "1"

    def transcribe(self, samples, sample_rate):
        return [("Hello there.", 0.0, 1.0)]


class FakeDetector:
    def __init__(self, score):
        self.score = score

    def score_windows(self, windows, sample_rate):
        return [self.score] * len(windows)


def write_wav(path, amplitude=0.2, seconds=3):
    rate = 16_000
    times = np.arange(rate * seconds) / rate
    samples = (amplitude * np.sin(2 * np.pi * 220 * times) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return path


@pytest.mark.parametrize(
    ("head", "container"),
    [
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "wav"),
        (b"ID3\x04\x00\x00\x00\x00\x00\x00\x00\x00", "mpeg"),
        (b"\xff\xfb\x90\x00\x00\x00\x00\x00", "mpeg"),
        (b"fLaC\x00\x00\x00\x22", "flac"),
        (b"OggS\x00\x02\x00\x00", "ogg"),
        (b"\x00\x00\x00\x20ftypM4A \x00\x00", "m4a"),
    ],
)
def test_audio_is_identified_from_its_content(head, container):
    assert sniff_media_type(head) == (MediaType.AUDIO, container)


def test_jpeg_is_not_mistaken_for_mpeg_audio():
    assert sniff_media_type(b"\xff\xd8\xff\xe0\x00\x10JFIF") == (MediaType.IMAGE, "jpeg")


def test_an_audio_file_gets_speech_checks_and_no_score(tmp_path):
    result = analyze_media(
        write_wav(tmp_path / "voice.wav"),
        transcriber=FakeTranscriber(),
        audio_detectors=[("fake/a", "1", FakeDetector(0.9)), ("fake/b", "1", FakeDetector(0.8))],
    )
    assert result.media_type is MediaType.AUDIO
    assert result.status is CheckStatus.COMPLETE
    assert result.score is None
    assert result.assessment is Assessment.INCONCLUSIVE
    assert result.checks.classifier.status is CheckStatus.NOT_APPLICABLE
    assert result.checks.speech.segments[0].text == "Hello there."
    assert result.extracted_text["speech"][0]["text"] == "Hello there."
    assert [d.score_mean for d in result.checks.audio_synthetic.detectors] == [0.9, 0.8]
    assert result.failure_code is None


def test_strong_disagreement_between_models_is_reported(tmp_path):
    result = analyze_media(
        write_wav(tmp_path / "voice.wav"),
        transcriber=FakeTranscriber(),
        audio_detectors=[("fake/a", "1", FakeDetector(0.0)), ("fake/b", "1", FakeDetector(1.0))],
    )
    assert any("disagree" in line for line in result.checks.audio_synthetic.limitations)


def test_silent_audio_is_not_sent_to_the_models(tmp_path):
    result = analyze_media(
        write_wav(tmp_path / "silent.wav", amplitude=0.0),
        transcriber=FakeTranscriber(),
        audio_detectors=[("fake/a", "1", FakeDetector(0.9))],
    )
    assert result.checks.speech.segments == []
    assert result.checks.audio_synthetic.status is CheckStatus.UNAVAILABLE


def test_a_broken_audio_file_is_rejected(tmp_path):
    path = tmp_path / "broken.wav"
    path.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 16)
    result = analyze_media(path, transcriber=FakeTranscriber(), audio_detectors=[])
    assert result.failure_code == "corrupt_media"
