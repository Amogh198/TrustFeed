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
    label: str = "Supporting evidence"
    url: str | None = None
    route: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_artifact(cls, value: Any) -> Any:
        """Accept artifacts emitted by the media, provenance and network lanes."""
        if not isinstance(value, dict):
            return value
        artifact = dict(value)
        artifact.setdefault("kind", artifact.get("type", "evidence"))
        artifact.setdefault("label", {
            "network_graph": "Network graph",
            "fingerprints": "Media fingerprints",
        }.get(artifact["kind"], "Supporting evidence"))
        return artifact


class ExplanationCheck(BaseModel):
    check_id: str
    module: str
    label: str
    legacy_alias: bool = False
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

    @model_validator(mode="before")
    @classmethod
    def normalize_section(cls, value: Any) -> Any:
        if isinstance(value, dict):
            val = dict(value)
            if "heading" not in val and "title" in val:
                val["heading"] = str(val["title"])
            if "items" not in val and "content" in val:
                content = val["content"]
                val["items"] = [content] if isinstance(content, str) else list(content)
            return val
        return value


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
