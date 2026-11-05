from datetime import datetime, timezone
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


class ModuleResult(BaseModel):
    status: ModuleStatus
    score: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    text: str | None = Field(default=None, max_length=20_000)
    url: HttpUrl | None = None

    @model_validator(mode="after")
    def require_input(self) -> "AnalyzeRequest":
        if not (self.text and self.text.strip()) and not self.url:
            raise ValueError("Provide non-empty text, a URL, or both")
        return self


class AnalysisResponse(BaseModel):
    case_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    overall_risk: RiskLevel
    summary: str
    modules: dict[str, ModuleResult]
    uncertainties: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


class ActionPacketRequest(BaseModel):
    audience: str = Field(default="public", max_length=80)


class ActionPacketResponse(BaseModel):
    case_id: str
    generated: bool = False
    label: str = "Template only; not generated or independently verified by an AI model."
    draft: str
    evidence_references: list[str] = Field(default_factory=list)
