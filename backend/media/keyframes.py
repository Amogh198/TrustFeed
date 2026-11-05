"""Scene-change keyframe sampling, so videos are not scored frame by frame."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from backend.media.config import MediaConfig
from backend.media.errors import MediaInputError

STRATEGY = "hsv-histogram-scene-change-with-periodic-floor"
_FALLBACK_FPS = 25.0
_MAX_FRAME_SIDE = 512


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    frame_count: int | None
    duration_s: float


@dataclass(frozen=True)
class Keyframe:
    frame_index: int
    timestamp_s: float
    scene_change_score: float
    image: object


def _histogram(cv2, frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    cv2.normalize(histogram, histogram)
    return histogram


def _to_pil(cv2, frame):
    from PIL import Image

    height, width = frame.shape[:2]
    scale = _MAX_FRAME_SIDE / max(height, width)
    if scale < 1:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def extract_keyframes(path: Path, config: MediaConfig) -> tuple[VideoInfo, list[Keyframe], list[str]]:
    import cv2

    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise MediaInputError("corrupt_media", "The video is corrupt or could not be decoded.")

        limitations: list[str] = []
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0 or fps > 1000:
            fps = _FALLBACK_FPS
            limitations.append("The video reports an invalid frame rate, so timestamps are approximate.")
        reported_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        step = max(1, round(fps / config.sample_fps))
        frame_limit = int(config.max_video_seconds * fps)

        keyframes: list[Keyframe] = []
        kept_histogram = None
        kept_at: float | None = None
        frames_seen = 0
        hit_time_limit = False
        dropped = False

        while capture.grab():
            frame_index = frames_seen
            if frame_index >= frame_limit:
                hit_time_limit = True
                break
            frames_seen += 1
            if frame_index % step:
                continue
            ok, frame = capture.retrieve()
            if not ok or frame is None:
                continue

            timestamp = frame_index / fps
            histogram = _histogram(cv2, frame)
            if kept_at is None:
                change = 1.0
                keep = True
            else:
                # Compare with the last kept frame so gradual changes still add up.
                change = float(cv2.compareHist(kept_histogram, histogram, cv2.HISTCMP_BHATTACHARYYA))
                gap = timestamp - kept_at
                keep = (change >= config.scene_change_threshold and gap >= config.min_keyframe_gap_s) or (
                    gap >= config.max_keyframe_gap_s
                )
            if not keep:
                continue

            keyframes.append(Keyframe(frame_index, round(timestamp, 3), round(change, 4), _to_pil(cv2, frame)))
            kept_histogram = histogram
            kept_at = timestamp
            if len(keyframes) > config.max_keyframes:
                # Keep the opening frame and the strongest scene changes.
                keyframes.remove(min(keyframes[1:], key=lambda item: item.scene_change_score))
                dropped = True

        if not keyframes:
            raise MediaInputError("corrupt_media", "The video is corrupt or contains no decodable frames.")

        if hit_time_limit:
            limitations.append(f"Only the first {config.max_video_seconds:.0f} seconds were analyzed.")
        elif reported_count > 0 and frames_seen < reported_count * 0.9:
            limitations.append("The video ended earlier than its header reports; it may be truncated.")
        if dropped:
            limitations.append(f"Keyframes were capped at {config.max_keyframes}, so some scenes were not analyzed.")
        limitations.append("Only sampled keyframes were analyzed; manipulation between keyframes can be missed.")

        duration = (reported_count if reported_count > 0 else frames_seen) / fps
        info = VideoInfo(
            width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=round(fps, 3),
            frame_count=reported_count if reported_count > 0 else None,
            duration_s=round(duration, 3),
        )
        return info, keyframes, limitations
    finally:
        capture.release()
