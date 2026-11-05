"""Internal result models for the media lane.

These are deliberately separate from the shared API models.
``MediaAnalysisResult.to_module_result`` produces the contract-shaped payload.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CheckStatus(StrEnum):
    COMPLETE = "complete"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    UNKNOWN = "unknown"


class Assessment(StrEnum):
    """Triage outcome. There is intentionally no real/fake value."""

    SIGNALS_PRESENT = "signals_present"
    NO_STRONG_SIGNALS = "no_strong_signals"
    INCONCLUSIVE = "inconclusive"


class ModelBand(StrEnum):
    ELEVATED = "elevated"
    LOW = "low"
    INCONCLUSIVE = "inconclusive"


class HashMatch(BaseModel):
    phash: str
    distance: int
    label: str
    first_seen: str | None = None
    source: str | None = None
    timestamp_s: float | None = None


class MetadataCheck(BaseModel):
    status: CheckStatus
    format: str | None = None
    width: int | None = None
    height: int | None = None
    exif_present: bool | None = None
    fields: dict[str, str] = Field(default_factory=dict)
    # Whether GPS data exists. Coordinates are never copied into results.
    has_gps: bool | None = None
    generator_hint: bool = False
    indicators: list[str] = Field(default_factory=list)
    fps: float | None = None
    frame_count: int | None = None
    duration_s: float | None = None
    limitations: list[str] = Field(default_factory=list)


class ClassifierCheck(BaseModel):
    status: CheckStatus
    model_id: str | None = None
    model_revision: str | None = None
    score: float | None = None
    score_min: float | None = None
    score_max: float | None = None
    band: ModelBand | None = None
    items_scored: int = 0
    limitations: list[str] = Field(default_factory=list)


class PHashCheck(BaseModel):
    status: CheckStatus
    phash: str | None = None
    compared: bool = False
    references_checked: int = 0
    max_distance: int | None = None
    matches: list[HashMatch] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FrameEvidence(BaseModel):
    frame_index: int
    timestamp_s: float
    scene_change_score: float
    phash: str | None = None
    model_score: float | None = None


class KeyframeCheck(BaseModel):
    status: CheckStatus
    strategy: str | None = None
    frames: list[FrameEvidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MediaChecks(BaseModel):
    metadata: MetadataCheck
    classifier: ClassifierCheck
    phash: PHashCheck
    keyframes: KeyframeCheck


def _not_run(reason: str) -> dict[str, Any]:
    return {"status": CheckStatus.UNAVAILABLE, "limitations": [reason]}


def empty_checks(reason: str) -> MediaChecks:
    return MediaChecks(
        metadata=MetadataCheck(**_not_run(reason)),
        classifier=ClassifierCheck(**_not_run(reason)),
        phash=PHashCheck(**_not_run(reason)),
        keyframes=KeyframeCheck(**_not_run(reason)),
    )


class MediaAnalysisResult(BaseModel):
    schema_version: str = "media-1"
    media_type: MediaType
    status: CheckStatus
    # Model signal only. It stays null when no model result exists, even if
    # metadata or pHash produced evidence.
    score: float | None = None
    # Always null: the model's probabilities have not been calibrated.
    confidence: float | None = None
    assessment: Assessment
    summary: str
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    failure_code: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    checks: MediaChecks

    def to_module_result(self) -> dict[str, Any]:
        """Return the shared `ModuleResult` shape from API_CONTRACTS.md."""
        return {
            "status": self.status.value,
            "score": self.score,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "limitations": list(self.limitations),
        }

    def to_checks(self, *, heatmap_url: str | None = None) -> list[dict[str, Any]]:
        """Return one explanation check for each media check, for the explanation route."""
        from backend.media.explain import build_checks

        return build_checks(self, heatmap_url=heatmap_url)
