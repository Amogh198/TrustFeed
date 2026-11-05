from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, model_validator


class RiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"
    INCONCLUSIVE = "inconclusive"


class ModuleStatus(StrEnum):
    COMPLETE = "complete"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class ClaimVerdict(StrEnum):
    UNVERIFIED = "unverified"


class ModuleResult(BaseModel):
    status: ModuleStatus
    score: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ClaimRecord(BaseModel):
    id: str
    text: str
    verdict: ClaimVerdict = ClaimVerdict.UNVERIFIED
    rationale: str = "No external evidence source was queried for this claim."


class AnalyzeRequest(BaseModel):
    text: str | None = Field(default=None, max_length=20_000)
    url: HttpUrl | None = None
    # Sends the text and link to public platforms' search services, so it is off by default.
    search_web: bool = False

    @model_validator(mode="after")
    def require_input(self) -> "AnalyzeRequest":
        if not (self.text and self.text.strip()) and not self.url:
            raise ValueError("Provide non-empty text, a URL, or both")
        return self


class AnalysisResponse(BaseModel):
    case_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    overall_risk: RiskLevel
    summary: str
    modules: dict[str, ModuleResult]
    claims: list[ClaimRecord] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    is_replay: bool = False
    replay_label: str | None = None


class TimelineEvent(BaseModel):
    # Undated events stay in the list with a null time. A date is never invented.
    at: str | None = None
    kind: str
    label: str
    module: str
    ref: str
    date_source: str
    synthetic: bool = False


class TimelineResponse(BaseModel):
    events: list[TimelineEvent]


class ExplanationArtifact(BaseModel):
    kind: str
    label: str
    url: str | None = None


class ExplanationCheck(BaseModel):
    check_id: str
    module: str
    label: str
    status: str | None = None
    result: str
    reasoning: str | list[str]
    benchmark: dict[str, Any] | None = None
    artifacts: list[ExplanationArtifact] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MissingCheck(BaseModel):
    module: str
    status: str
    reason: str


class ExplanationResponse(BaseModel):
    case_id: str
    checks: list[ExplanationCheck]
    missing_checks: list[MissingCheck] = Field(default_factory=list)
    what_was_submitted: list[str]
    what_was_detected: list[str]
    supports: list[str]
    refutes: list[str]
    uncertainties: list[str]


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


class ActionPacketRequest(BaseModel):
    audience: str = Field(default="public", max_length=80)


class ActionPacketSection(BaseModel):
    heading: str
    items: list[str]


class ActionPacketResponse(BaseModel):
    case_id: str
    generated: bool = False
    label: str = "Template only; not generated or independently verified by an AI model."
    draft: str
    evidence_references: list[str] = Field(default_factory=list)
    sections: list[ActionPacketSection] = Field(default_factory=list)


class CaseSummary(BaseModel):
    case_id: str
    created_at: datetime
    overall_risk: RiskLevel
    summary: str
    is_replay: bool = False
    replay_label: str | None = None


class CaseHistoryResponse(BaseModel):
    cases: list[CaseSummary]
    total: int


class MonitorStartRequest(BaseModel):
    # Polling sends these terms to outside services, so it must be asked for explicitly.
    opted_in: bool
    text: str | None = Field(default=None, max_length=2_000)
    urls: list[HttpUrl] = Field(default_factory=list, max_length=5)
    hashtags: list[str] = Field(default_factory=list, max_length=5)


class HeatmapResponse(BaseModel):
    status: str
    label: str
    grid_size: int
    base_score: float | None = None
    max_change: float | None = None
    notable: bool = False
    reasoning: str
    limitations: list[str] = Field(default_factory=list)
    # A transparent colour grid with none of the image's pixels, to lay over its preview.
    png_base64: str | None = None


class ReplayScenario(BaseModel):
    id: str
    title: str
    description: str
    label: str


class ReplayScenariosResponse(BaseModel):
    scenarios: list[ReplayScenario]
