from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from backend.media.nonescape import NONESCAPE_MODEL_ID, NONESCAPE_SHA256

# The best single detector on data/eval/commons_licensed_2026-11-05.json: AUC 0.69 [0.63-0.75].
DEFAULT_MODEL_ID = NONESCAPE_MODEL_ID
# Pinned so a demo cannot change behaviour when the upstream file changes.
DEFAULT_MODEL_REVISION = NONESCAPE_SHA256

_MB = 1024 * 1024
_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MediaConfig:
    model_id: str = DEFAULT_MODEL_ID
    model_revision: str | None = DEFAULT_MODEL_REVISION
    # Off by default: analysis must never start a large download mid-request.
    allow_model_download: bool = False
    device: str = "auto"
    batch_size: int = 8

    phash_index_path: Path | None = None
    phash_max_distance: int = 5
    # Hashes of earlier cases, never the uploads. Not set means no comparison with earlier cases.
    case_fingerprints_path: Path | None = None

    max_image_bytes: int = 25 * _MB
    max_video_bytes: int = 200 * _MB
    max_image_pixels: int = 50_000_000
    # Below this the classifier input is mostly upscaled, so its score is not trusted.
    min_reliable_side: int = 128

    sample_fps: float = 2.0
    scene_change_threshold: float = 0.35
    min_keyframe_gap_s: float = 1.0
    max_keyframe_gap_s: float = 10.0
    max_keyframes: int = 16
    max_video_seconds: float = 600.0

    # Scores between these bounds are reported as inconclusive.
    elevated_score: float = 0.75
    low_score: float = 0.25
    # Keyframes further apart than this make a video's model result inconclusive.
    frame_disagreement: float = 0.5

    # No further panel detector starts after this long. One already running finishes.
    panel_time_budget_s: float = 180.0

    # Reading a file's Content Credentials stops after this long, and the check says so.
    c2pa_time_limit_s: float = 30.0
    # A PEM file of certificate authorities. Not set means signers are not checked against a list.
    c2pa_trust_list_path: Path | None = None

    # Pixel forensics stop after this long, and the check says so.
    forensics_time_limit_s: float = 20.0

    faces_time_limit_s: float = 30.0
    max_faces: int = 8

    # Not set means looking for the Tesseract program on the PATH.
    tesseract_cmd: str | None = None
    ocr_languages: str = "eng"
    ocr_time_limit_s: float = 30.0

    # Speech-to-text, synthetic speech and frame by frame scoring are slow on CPU, so they run on request.
    run_heavy_checks: bool = False
    frames_per_second: float = 1.0
    max_scored_frames: int = 120
    frames_time_limit_s: float = 120.0
    max_audio_seconds: float = 600.0
    speech_time_limit_s: float = 300.0
    audio_time_limit_s: float = 120.0

    @classmethod
    def from_env(cls) -> MediaConfig:
        model_id = os.environ.get("MEDIA_MODEL_ID", "").strip()
        revision = os.environ.get("MEDIA_MODEL_REVISION", "").strip()
        index = os.environ.get("MEDIA_PHASH_INDEX", "").strip()
        allow = os.environ.get("MEDIA_ALLOW_MODEL_DOWNLOAD", "").strip().casefold()
        cases = os.environ.get("MEDIA_CASE_FINGERPRINTS", "").strip()
        trust_list = os.environ.get("MEDIA_C2PA_TRUST_LIST", "").strip()
        heavy = os.environ.get("MEDIA_RUN_HEAVY_CHECKS", "").strip().casefold()
        return cls(
            tesseract_cmd=os.environ.get("MEDIA_TESSERACT_CMD", "").strip() or None,
            ocr_languages=os.environ.get("MEDIA_OCR_LANGUAGES", "").strip() or "eng",
            run_heavy_checks=heavy in _TRUTHY,
            model_id=model_id or DEFAULT_MODEL_ID,
            # The pinned revision only applies to the default model.
            model_revision=revision or (None if model_id else DEFAULT_MODEL_REVISION),
            allow_model_download=allow in _TRUTHY,
            device=os.environ.get("MEDIA_DEVICE", "").strip() or "auto",
            phash_index_path=Path(index) if index else None,
            case_fingerprints_path=Path(cases) if cases else None,
            c2pa_trust_list_path=Path(trust_list) if trust_list else None,
        )
