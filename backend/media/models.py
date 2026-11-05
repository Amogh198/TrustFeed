"""Internal result models for the media lane.

These are deliberately separate from the shared API models.
``MediaAnalysisResult.to_module_result`` produces the contract-shaped payload.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_serializer


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
    fingerprints: dict[str, str] = Field(default_factory=dict)


class FingerprintMatch(BaseModel):
    # "exact_copy" means the same file. "likely_same_image" means the same picture, possibly changed.
    kind: str
    # "reference" or "earlier_case".
    found_in: str
    label: str | None = None
    case_id: str | None = None
    # The earliest date recorded for this entry, not when the image first existed.
    first_seen: str | None = None
    source: str | None = None
    distances: dict[str, int] = Field(default_factory=dict)
    timestamp_s: float | None = None


class FingerprintCheck(BaseModel):
    status: CheckStatus
    sha256: str | None = None
    hashes: dict[str, str] = Field(default_factory=dict)
    frames_hashed: int = 0
    compared: bool = False
    references_checked: int = 0
    earlier_cases_checked: int = 0
    matches: list[FingerprintMatch] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class KeyframeCheck(BaseModel):
    status: CheckStatus
    strategy: str | None = None
    frames: list[FrameEvidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class DetectorResult(BaseModel):
    """One detector's own result. Only the detector in use affects the overall score."""

    model_id: str
    model_revision: str | None = None
    status: CheckStatus
    score: float | None = None
    band: ModelBand | None = None
    counted: bool = False
    limitations: list[str] = Field(default_factory=list)


class DetectorPanelCheck(BaseModel):
    status: CheckStatus
    detectors: list[DetectorResult] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ContentCredentialsCheck(BaseModel):
    """What a file's Content Credentials show. Manifest text is written by whoever made the file."""

    status: CheckStatus
    # "signed", "unsigned" or "invalid". Null when it could not be told, with the reason in limitations.
    state: str | None = None
    # "on_trust_list", "not_on_trust_list" or "not_checked". Null unless signed.
    signer_trust: str | None = None
    # "content_changed", "rules_failed" or "credentials_failed". Null unless invalid.
    invalid_reason: str | None = None
    signer_organisation: str | None = None
    claim_generator: str | None = None
    signed_at: str | None = None
    # How the newest manifest says the media was made, then what earlier steps in its history say.
    declared_sources: list[str] = Field(default_factory=list)
    declared_in_history: list[str] = Field(default_factory=list)
    failure_codes: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ForensicRegion(BaseModel):
    """A box in the image's own pixels where a test's reading stood out. It doesn't show that the area was edited."""

    x: int
    y: int
    width: int
    height: int


class ForensicTest(BaseModel):
    name: str
    status: CheckStatus
    score: float | None = None
    # The score at which this test reads as unusual. Null if no limit has been measured.
    limit: float | None = None
    # Null when the test did not run, or has no limit.
    flagged: bool | None = None
    regions: list[ForensicRegion] = Field(default_factory=list)
    reason: str | None = None


class ForensicsCheck(BaseModel):
    status: CheckStatus
    source_format: str | None = None
    jpeg_quality_estimate: int | None = None
    tests: list[ForensicTest] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MediaChecks(BaseModel):
    metadata: MetadataCheck
    classifier: ClassifierCheck
    phash: PHashCheck
    keyframes: KeyframeCheck
    # Only present when requested, because running every detector is slow on CPU.
    detector_panel: DetectorPanelCheck | None = None
    fingerprint: FingerprintCheck | None = None
    content_credentials: ContentCredentialsCheck | None = None
    forensics: ForensicsCheck | None = None

    @model_serializer(mode="wrap")
    def _leave_out_checks_that_did_not_run(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        for name in ("detector_panel", "fingerprint", "content_credentials", "forensics"):
            if data.get(name) is None:
                data.pop(name, None)
        return data


def _not_run(reason: str) -> dict[str, Any]:
    return {"status": CheckStatus.UNAVAILABLE, "limitations": [reason]}


def empty_checks(reason: str) -> MediaChecks:
    return MediaChecks(
        metadata=MetadataCheck(**_not_run(reason)),
        classifier=ClassifierCheck(**_not_run(reason)),
        phash=PHashCheck(**_not_run(reason)),
        keyframes=KeyframeCheck(**_not_run(reason)),
        fingerprint=FingerprintCheck(**_not_run(reason)),
        content_credentials=ContentCredentialsCheck(**_not_run(reason)),
        forensics=ForensicsCheck(**_not_run(reason)),
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
