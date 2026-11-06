"""Audio from a video, speech-to-text and synthetic speech signals. Every model loads only when needed.

Each model is pinned to a commit and loads from safetensors only. Nothing downloads during an analysis.
"""

from __future__ import annotations

import gc
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from backend.media.classifier import synthetic_class_index
from backend.media.config import MediaConfig
from backend.media.errors import ClassifierUnavailable
from backend.media.models import AudioDetectorResult, AudioSyntheticCheck, CheckStatus, SpeechCheck, SpeechSegment
from backend.media.ocr import clean_line

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
SPEECH_MODEL = ("openai/whisper-small", "973afd24965f72e36ca33b3055d56a652f456b4d")
AUDIO_DETECTORS: tuple[tuple[str, str], ...] = (
    ("MelodyMachine/Deepfake-audio-detection-V2", "de3cde5a29c449bb5268814e421b46bf6ebdcd72"),
    ("motheecreator/Deepfake-audio-detection", "e4d9874b493362149cec96ced85f00b00b1a04c0"),
)
MODEL_FILES = ["model.safetensors", "*.json", "merges.txt", "vocab.txt"]
# Below this average level a track is treated as silent, where speech models tend to invent text.
SILENCE_RMS = 1e-3
WINDOW_S = 10
MAX_WINDOWS = 6
MIN_WINDOW_S = 1.0
DISAGREEMENT = 0.5
SPEECH_LIMITATIONS = (
    "Speech-to-text can mishear words and can invent words in noise or music. Check anything important by listening.",
    "Accuracy has not been measured.",
)
SYNTHETIC_LIMITATIONS = (
    "Measured once, on 150 labelled clips from one public set: motheecreator/Deepfake-audio-detection reached AUC 0.80 and "
    "wrongly flagged 24 of 75 real clips, and MelodyMachine/Deepfake-audio-detection-V2 did no better than guessing (AUC 0.44). "
    "These scores are signals, not proof that speech is real or synthetic.",
    "Each model gives its own signal. They aren't combined, and they don't change the overall score or assessment.",
)


class AudioUnavailable(Exception):
    """Audio can't be read. The message is safe to show."""


class AudioReaderMissing(AudioUnavailable):
    """PyAV isn't installed, which says nothing about the file."""


@dataclass
class AudioTrack:
    samples: Any
    duration_s: float
    truncated: bool
    sample_rate: int = SAMPLE_RATE


def extract_audio(path: Path, config: MediaConfig) -> AudioTrack | None:
    """Return the first audio track as 16 kHz mono, or None if the file has no audio."""
    try:
        import av
        import numpy as np
    except ImportError as exc:
        raise AudioReaderMissing("Reading audio needs PyAV, which isn't installed.") from exc
    limit = int(config.max_audio_seconds * SAMPLE_RATE)
    parts: list[Any] = []
    total = 0
    truncated = False
    try:
        with av.open(str(path)) as container:
            stream = next((item for item in container.streams if item.type == "audio"), None)
            if stream is None:
                return None
            resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(stream):
                for output in resampler.resample(frame):
                    part = output.to_ndarray().ravel()
                    parts.append(part)
                    total += part.size
                if total >= limit:
                    truncated = True
                    break
            if not truncated:
                for output in resampler.resample(None):
                    part = output.to_ndarray().ravel()
                    parts.append(part)
                    total += part.size
    except (av.FFmpegError, OSError, ValueError) as exc:
        logger.warning("Audio could not be read: %s", type(exc).__name__)
        raise AudioUnavailable("The audio could not be decoded.") from None
    if not parts:
        return None
    samples = np.concatenate(parts)[:limit].astype(np.float32)
    return AudioTrack(samples, round(samples.size / SAMPLE_RATE, 3), truncated)


def is_silent(track: AudioTrack) -> bool:
    import numpy as np

    return bool(track.samples.size == 0 or float(np.sqrt(np.mean(np.square(track.samples)))) < SILENCE_RMS)


class SpeechTranscriber(Protocol):
    model_id: str
    model_revision: str | None

    def transcribe(self, samples: Any, sample_rate: int) -> list[tuple[str, float, float | None]]:
        """Return (text, start, end) for each piece of speech."""
        ...


class WhisperTranscriber:
    def __init__(self, config: MediaConfig) -> None:
        self.model_id, self.model_revision = SPEECH_MODEL
        self._allow_download = config.allow_model_download

    def transcribe(self, samples: Any, sample_rate: int) -> list[tuple[str, float, float | None]]:
        try:
            from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
        except Exception as exc:
            raise ClassifierUnavailable("Speech-to-text needs transformers, which isn't installed.") from exc
        options = {"revision": self.model_revision, "local_files_only": not self._allow_download}
        try:
            processor = AutoProcessor.from_pretrained(self.model_id, **options)
            model = AutoModelForSpeechSeq2Seq.from_pretrained(self.model_id, use_safetensors=True, **options)
        except Exception as exc:
            raise ClassifierUnavailable(
                "Speech-to-text weights aren't available locally. Run: python -m backend.media download-audio"
            ) from exc
        reader = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            chunk_length_s=30,
            device="cpu",
        )
        output = reader(
            {"raw": samples, "sampling_rate": sample_rate},
            return_timestamps=True,
            generate_kwargs={"task": "transcribe"},
        )
        pieces = []
        for chunk in output.get("chunks", []):
            start, end = chunk.get("timestamp", (None, None))
            pieces.append((chunk.get("text", ""), float(start or 0.0), float(end) if end is not None else None))
        del reader, model, processor
        gc.collect()
        return pieces


def transcribe_speech(track: AudioTrack | None, config: MediaConfig, transcriber: SpeechTranscriber) -> SpeechCheck:
    """Report what was said, with times. Failures are reported, never raised."""
    identity = {"model_id": transcriber.model_id, "model_revision": transcriber.model_revision}
    if track is None:
        return SpeechCheck(status=CheckStatus.COMPLETE, has_audio=False, limitations=["This video has no audio track."], **identity)
    limitations = list(SPEECH_LIMITATIONS)
    if track.truncated:
        limitations.append(f"Only the first {config.max_audio_seconds:.0f} seconds of audio were read.")
    if is_silent(track):
        limitations.append("The audio is silent or nearly silent, so no speech-to-text was run.")
        return SpeechCheck(status=CheckStatus.COMPLETE, has_audio=True, limitations=limitations, **identity)
    try:
        pieces = transcriber.transcribe(track.samples, track.sample_rate)
    except ClassifierUnavailable as exc:
        return SpeechCheck(status=CheckStatus.UNAVAILABLE, limitations=[str(exc)], **identity)
    except Exception as exc:  # noqa: BLE001 - a model failure must be reported, never crash the request.
        logger.warning("Speech-to-text failed: %s", type(exc).__name__)
        return SpeechCheck(status=CheckStatus.UNAVAILABLE, limitations=["Speech-to-text failed unexpectedly."], **identity)
    segments = [
        SpeechSegment(text=text, start_s=round(start, 2), end_s=round(end, 2) if end is not None else None)
        for raw, start, end in pieces
        if (text := clean_line(raw))
    ]
    return SpeechCheck(status=CheckStatus.COMPLETE, has_audio=True, segments=segments, limitations=limitations, **identity)


class AudioDetector(Protocol):
    def score_windows(self, windows: Sequence[Any], sample_rate: int) -> list[float]:
        """Return the synthetic-class probability for each window."""
        ...


class HuggingFaceAudioDetector:
    def __init__(self, model_id: str, revision: str, config: MediaConfig) -> None:
        self.model_id, self.model_revision = model_id, revision
        self._allow_download = config.allow_model_download

    def score_windows(self, windows: Sequence[Any], sample_rate: int) -> list[float]:
        try:
            import torch
            from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
        except Exception as exc:
            raise ClassifierUnavailable("Synthetic speech models need torch and transformers.") from exc
        options = {"revision": self.model_revision, "local_files_only": not self._allow_download}
        try:
            extractor = AutoFeatureExtractor.from_pretrained(self.model_id, **options)
            model = AutoModelForAudioClassification.from_pretrained(self.model_id, use_safetensors=True, **options)
        except Exception as exc:
            raise ClassifierUnavailable(
                "This model's weights aren't available locally. Run: python -m backend.media download-audio"
            ) from exc
        target = synthetic_class_index(model.config.id2label)
        model.eval()
        scores = []
        with torch.inference_mode():
            for window in windows:
                inputs = extractor(window, sampling_rate=sample_rate, return_tensors="pt")
                scores.append(float(torch.softmax(model(**inputs).logits, dim=-1)[0, target]))
        del model, extractor
        gc.collect()
        return scores


def choose_windows(track: AudioTrack) -> list[Any]:
    """Spread up to MAX_WINDOWS windows evenly over the track, leaving out silent ones."""
    size = WINDOW_S * track.sample_rate
    total = track.samples.size
    if total < MIN_WINDOW_S * track.sample_rate:
        return []
    count = min(MAX_WINDOWS, max(1, total // size))
    step = max(1, (total - size) // max(1, count - 1)) if count > 1 else 0
    windows = [track.samples[index * step : index * step + size] for index in range(count)]
    return [window for window in windows if not is_silent(AudioTrack(window, 0.0, False))]


def detect_synthetic_speech(
    track: AudioTrack | None,
    config: MediaConfig,
    detectors: Sequence[tuple[str, str, AudioDetector]] | None = None,
) -> AudioSyntheticCheck:
    """Run each model in turn, releasing it before the next. Failures are reported, never raised."""
    limitations = list(SYNTHETIC_LIMITATIONS)
    if track is None:
        return AudioSyntheticCheck(status=CheckStatus.NOT_APPLICABLE, limitations=["This video has no audio track."])
    windows = choose_windows(track)
    if not windows:
        return AudioSyntheticCheck(
            status=CheckStatus.UNAVAILABLE, limitations=["The audio is too short or too quiet to score."]
        )
    if detectors is None:
        detectors = [(m, r, HuggingFaceAudioDetector(m, r, config)) for m, r in AUDIO_DETECTORS]
    started = time.monotonic()
    results = []
    for model_id, revision, detector in detectors:
        if time.monotonic() - started >= config.audio_time_limit_s:
            results.append(
                AudioDetectorResult(
                    model_id=model_id,
                    model_revision=revision,
                    status=CheckStatus.UNAVAILABLE,
                    reason=f"Not run: the {config.audio_time_limit_s:.0f}-second limit was reached.",
                )
            )
            continue
        results.append(_score_detector(model_id, revision, detector, windows, track.sample_rate))
    ran = any(result.status is CheckStatus.COMPLETE for result in results)
    means = [result.score_mean for result in results if result.score_mean is not None]
    if len(means) > 1 and max(means) - min(means) >= DISAGREEMENT:
        limitations.append("The models disagree strongly on this audio, so these scores say little here.")
    return AudioSyntheticCheck(
        status=CheckStatus.COMPLETE if ran else CheckStatus.UNAVAILABLE, detectors=results, limitations=limitations
    )


def _score_detector(model_id: str, revision: str, detector: AudioDetector, windows: Sequence[Any], rate: int) -> AudioDetectorResult:
    identity = {"model_id": model_id, "model_revision": revision}
    try:
        scores = detector.score_windows(windows, rate)
    except ClassifierUnavailable as exc:
        return AudioDetectorResult(status=CheckStatus.UNAVAILABLE, reason=str(exc), **identity)
    except Exception as exc:  # noqa: BLE001 - the other model still runs.
        logger.warning("Synthetic speech model failed: %s", type(exc).__name__)
        return AudioDetectorResult(status=CheckStatus.UNAVAILABLE, reason="The model failed unexpectedly.", **identity)
    if len(scores) != len(windows) or not all(0 <= score <= 1 for score in scores):
        return AudioDetectorResult(status=CheckStatus.UNAVAILABLE, reason="The model returned invalid output.", **identity)
    return AudioDetectorResult(
        status=CheckStatus.COMPLETE,
        score_mean=round(sum(scores) / len(scores), 4),
        score_max=round(max(scores), 4),
        windows_scored=len(scores),
        **identity,
    )


def download_audio_models() -> list[str]:
    """Download the speech and synthetic speech models for offline use. Analysis never calls this."""
    from huggingface_hub import snapshot_download

    return [
        # One worker, because parallel workers can fail on Windows without symlink rights.
        snapshot_download(model_id, revision=revision, allow_patterns=MODEL_FILES, max_workers=1)
        for model_id, revision in (SPEECH_MODEL, *AUDIO_DETECTORS)
    ]
