"""Score a video frame by frame, list suspicious sections, and report changes across frames.

Accuracy on video has not been measured. Nothing here changes the overall score or assessment.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backend.media.config import MediaConfig
from backend.media.errors import ClassifierUnavailable
from backend.media.keyframes import _to_pil
from backend.media.models import CheckStatus, FrameScore, FramesCheck, ScoreChange, SuspiciousSection

logger = logging.getLogger(__name__)

# A sudden jump in score at least this large is listed, up to this many.
NOTABLE_JUMP = 0.3
MAX_CHANGES = 5
# This many quiet frames in a row can sit inside one suspicious section.
SECTION_GAP = 1
LIP_SYNC_NOTE = (
    "Lip-sync was not checked. It is not available, because no detection model with both a clear licence and a safe "
    "weight format was found."
)
FRAMES_LIMITATIONS = (
    "Accuracy on video has not been measured, so a suspicious section is an unmeasured signal, not proof.",
    "This does not change the overall score or assessment.",
    LIP_SYNC_NOTE,
)


def find_sections(frames: Sequence[FrameScore], limit: float) -> list[SuspiciousSection]:
    """Group frames at or above the limit, allowing a short gap, so one quiet frame doesn't split a section."""
    sections: list[SuspiciousSection] = []
    current: list[FrameScore] = []
    gap = 0
    for frame in frames:
        if frame.score >= limit:
            current.append(frame)
            gap = 0
        elif current:
            gap += 1
            if gap > SECTION_GAP:
                sections.append(_section(current))
                current, gap = [], 0
    if current:
        sections.append(_section(current))
    return sections


def _section(frames: Sequence[FrameScore]) -> SuspiciousSection:
    return SuspiciousSection(
        start_s=frames[0].timestamp_s,
        end_s=frames[-1].timestamp_s,
        frames=len(frames),
        strongest=max(frame.score for frame in frames),
    )


def find_changes(frames: Sequence[FrameScore]) -> list[ScoreChange]:
    """The largest sudden jumps in score between neighbouring frames, biggest first."""
    jumps = [
        ScoreChange(
            from_s=before.timestamp_s,
            to_s=after.timestamp_s,
            change=round(after.score - before.score, 4),
            scene_change=after.scene_change,
        )
        for before, after in zip(frames, frames[1:], strict=False)
        if abs(after.score - before.score) >= NOTABLE_JUMP
    ]
    return sorted(jumps, key=lambda jump: abs(jump.change), reverse=True)[:MAX_CHANGES]


def _sample_step(capture: Any, cv2: Any, fps: float, config: MediaConfig) -> int:
    step = max(1, round(fps / config.frames_per_second))
    reported = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if reported > 0:
        # Spread the frames over a long video, rather than stopping part way through it.
        step = max(step, math.ceil(reported / config.max_scored_frames))
    return step


def score_frames(path: Path, classifier: Any, config: MediaConfig) -> FramesCheck:
    """Failures are reported, never raised. If the time limit is reached, the frames already scored are kept."""
    try:
        import cv2
    except ImportError:
        return FramesCheck(status=CheckStatus.UNAVAILABLE, limitations=["Scoring frames needs OpenCV, which isn't installed."])
    limitations = list(FRAMES_LIMITATIONS)
    capture = cv2.VideoCapture(str(path))
    started = time.monotonic()
    scored: list[FrameScore] = []
    try:
        if not capture.isOpened():
            return FramesCheck(status=CheckStatus.UNAVAILABLE, limitations=["The video could not be opened."])
        fps = capture.get(cv2.CAP_PROP_FPS)
        fps = fps if math.isfinite(fps) and 0 < fps <= 1000 else 25.0
        step = _sample_step(capture, cv2, fps, config)
        previous = None
        batch: list[tuple[float, float, Any]] = []
        index = 0
        stopped = False
        while capture.grab():
            position = index
            index += 1
            if position % step:
                continue
            if len(scored) + len(batch) >= config.max_scored_frames:
                limitations.append(f"Only {config.max_scored_frames} frames were scored.")
                break
            ok, frame = capture.retrieve()
            if not ok or frame is None:
                continue
            histogram = cv2.calcHist([cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)], [0, 1], None, [32, 32], [0, 180, 0, 256])
            cv2.normalize(histogram, histogram)
            change = 0.0 if previous is None else float(cv2.compareHist(previous, histogram, cv2.HISTCMP_BHATTACHARYYA))
            previous = histogram
            batch.append((round(position / fps, 3), round(change, 4), _to_pil(cv2, frame)))
            if len(batch) >= max(1, config.batch_size):
                scored.extend(_score_batch(classifier, batch))
                batch = []
                if time.monotonic() - started >= config.frames_time_limit_s:
                    stopped = True
                    break
        if batch and not stopped:
            scored.extend(_score_batch(classifier, batch))
    except ClassifierUnavailable as exc:
        return FramesCheck(status=CheckStatus.UNAVAILABLE, limitations=[str(exc)])
    except Exception as exc:  # noqa: BLE001 - a model failure must be reported, never crash the request.
        logger.warning("Frame scoring failed: %s", type(exc).__name__)
        return FramesCheck(status=CheckStatus.UNAVAILABLE, limitations=["Frame by frame scoring failed unexpectedly."])
    finally:
        capture.release()
    if stopped:
        limitations.append(f"Stopped at the {config.frames_time_limit_s:.0f}-second limit, so later frames weren't scored.")
    if not scored:
        return FramesCheck(status=CheckStatus.UNAVAILABLE, limitations=["No frames could be scored."])
    ranked = sorted((frame.score for frame in scored), reverse=True)
    top = ranked[: max(1, math.ceil(len(ranked) / 3))]
    return FramesCheck(
        status=CheckStatus.COMPLETE,
        model_id=getattr(classifier, "model_id", None),
        model_revision=getattr(classifier, "model_revision", None),
        frames=scored,
        frames_elevated=sum(score >= config.elevated_score for score in ranked),
        video_score=round(sum(top) / len(top), 4),
        sections=find_sections(scored, config.elevated_score),
        changes=find_changes(scored),
        limitations=list(dict.fromkeys(limitations)),
    )


def _score_batch(classifier: Any, batch: Sequence[tuple[float, float, Any]]) -> list[FrameScore]:
    scores = classifier.predict([image for _, _, image in batch])
    if len(scores) != len(batch) or not all(0 <= score <= 1 for score in scores):
        raise ClassifierUnavailable("The detector returned invalid output.")
    return [
        FrameScore(timestamp_s=timestamp, score=round(float(score), 4), scene_change=change)
        for (timestamp, change, _), score in zip(batch, scores, strict=True)
    ]
