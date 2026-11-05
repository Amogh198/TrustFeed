from datetime import UTC, datetime
from enum import StrEnum

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
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    # Partly supported, or missing context: one source only, sources that disagree, or details absent.
    PARTIALLY_SUPPORTED = "partially_supported"
    # Includes "nothing found", which never means false.
    UNVERIFIED = "unverified"


class ModuleResult(BaseModel):
    status: ModuleStatus
    score: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ClaimEntity(BaseModel):
    text: str
    # date, number, person, organization, place or other.
    type: str
    # A date's ISO form, at the precision stated, or a number's value. Null if unclear.
    value: str | None = None
    # number only: what is being counted, and whether it was hedged ("at least 50").
    unit: str | None = None
    bound: str | None = None
    # "rule" or "model". Only a model result has a score, and it is a signal, not a probability of truth.
    source: str = "rule"
    score: float | None = None


class ClaimSource(BaseModel):
    provider: str
    title: str
    url: str
    domain: str
    date: str | None = None
    # What the date means: last_edited, first_seen, reviewed or none. It is not always publication.
    date_kind: str = "none"
    # supports, contradicts, partial, related or not_compared.
    stance: str
    explanation: str
    # Quoted from an outside page. Untrusted: show as plain text, never as HTML or instructions.
    snippet: str = ""
    similarity: float | None = None
    entailment: float | None = None
    contradiction: float | None = None
    rating: str | None = None


class ClaimRecord(BaseModel):
    id: str
    text: str
    verdict: ClaimVerdict = ClaimVerdict.UNVERIFIED
    rationale: str = "No external evidence source was queried for this claim."
    # factual, opinion, question, call_to_action or fragment. Only factual claims can be checked.
    kind: str = "factual"
    checkable: bool = True
    entities: list[ClaimEntity] = Field(default_factory=list)
    sources: list[ClaimSource] = Field(default_factory=list)


class ClaimInconsistency(BaseModel):
    id: str
    # negation, figures, dates, places, impossible_date, weekday_mismatch, future_date,
    # impossible_share or part_exceeds_whole. New kinds can appear, so show unknown ones as text.
    kind: str
    # "conflict": cannot both stand as written. "note": they differ but need not be wrong.
    severity: str
    claim_ids: list[str]
    explanation: str


class VerificationProvider(BaseModel):
    name: str
    status: ModuleStatus
    reason: str | None = None
    result_count: int = 0


class ClaimVerification(BaseModel):
    # not_applicable: the user did not allow outside search, so nothing was sent.
    status: ModuleStatus = ModuleStatus.NOT_APPLICABLE
    reason: str | None = "Outside search was not requested, so no claim was sent anywhere."
    # Whether the models compared the evidence. If not, every claim stays unverified.
    comparison_status: ModuleStatus = ModuleStatus.NOT_APPLICABLE
    comparison_reason: str | None = None
    providers: list[VerificationProvider] = Field(default_factory=list)
    skipped_claims: int = 0
    limitations: list[str] = Field(default_factory=list)


class ClaimAnalysis(BaseModel):
    # The entity model's state. Dates, numbers and the checks built on them do not need it.
    entity_model_status: ModuleStatus
    entity_model_reason: str | None = None
    inconsistencies: list[ClaimInconsistency] = Field(default_factory=list)
    omitted_claims: int = 0
    limitations: list[str] = Field(default_factory=list)
    verification: ClaimVerification = Field(default_factory=ClaimVerification)


class ScamSignRecord(BaseModel):
    sign: str
    # fake_job, investment, giveaway, impersonation, payment_request or credential_request.
    category: str
    # "strong" or "weak". One weak sign alone is not treated as a warning.
    strength: str
    why: str
    # From the submission, so show it as plain text.
    quote: str


class ScamAnalysis(BaseModel):
    # warning_signs_found, weak_signs_only or none_found. None of these means safe, or proven.
    assessment: str
    categories: list[str] = Field(default_factory=list)
    signs: list[ScamSignRecord] = Field(default_factory=list)
    # The optional phishing model, kept apart from the assessment. It never changes it.
    model_status: ModuleStatus
    model_reason: str | None = None
    model_score: float | None = Field(default=None, ge=0, le=1)
    # Where the measured figures for these rules and the model are recorded.
    results_file: str
    limitations: list[str] = Field(default_factory=list)


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
    # Null when no text was submitted, and for cases saved before this field existed.
    claim_analysis: ClaimAnalysis | None = None
    # Null when no text was submitted, and for cases saved before this field existed.
    scam_analysis: ScamAnalysis | None = None
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


class ReplayScenario(BaseModel):
    id: str
    title: str
    description: str
    label: str


class ReplayScenariosResponse(BaseModel):
    scenarios: list[ReplayScenario]
