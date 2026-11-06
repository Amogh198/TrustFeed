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


class LinkHop(BaseModel):
    # Without its query, which can hold private tokens.
    url: str
    host: str
    status: int


class LinkRedirects(BaseModel):
    status: ModuleStatus
    reason: str | None = None
    hops: list[LinkHop] = Field(default_factory=list)
    final_url: str | None = None
    final_host: str | None = None


class LinkDomainAge(BaseModel):
    status: ModuleStatus
    reason: str | None = None
    domain: str | None = None
    registered_on: str | None = None
    age_days: int | None = None
    source: str | None = None


class LinkPage(BaseModel):
    status: ModuleStatus
    reason: str | None = None
    http_status: int | None = None
    # Written by the page, so show it as plain text.
    title: str | None = None
    asks_for_login: bool = False
    asks_for_payment: bool = False
    asks_for_code: bool = False
    form_posts_to: list[str] = Field(default_factory=list)


class LinkLookalike(BaseModel):
    status: ModuleStatus
    host: str = ""
    # Set when the host really belongs to a listed brand.
    owned_by: str | None = None
    brand: str | None = None
    strength: str | None = None
    how: str | None = None
    official_domains: list[str] = Field(default_factory=list)


class LinkOfficialComparison(BaseModel):
    status: ModuleStatus
    reason: str | None = None
    brand: str | None = None
    official_domain: str | None = None
    official_title: str | None = None
    # Share of words in common, from 0 to 1. Uncalibrated.
    title_similarity: float | None = None
    text_similarity: float | None = None


class LinkThreatLists(BaseModel):
    status: ModuleStatus
    reason: str | None = None
    # Public feeds read, and how many addresses they held.
    sources: list[str] = Field(default_factory=list)
    entries: int = 0
    listed: bool = False


class LinkSign(BaseModel):
    sign: str
    # "strong" or "weak". One weak sign alone is not treated as a warning.
    strength: str
    why: str


class LinkAnalysis(BaseModel):
    # warning_signs_found, weak_signs_only or none_found. None of these means safe, or proven.
    assessment: str
    requested_host: str
    lookalike: LinkLookalike
    redirects: LinkRedirects
    domain: LinkDomainAge
    page: LinkPage
    official: LinkOfficialComparison
    threat_lists: LinkThreatLists
    # From the host name alone, 0 to 1. Null means the model didn't run. See link_model_train.json.
    model_score: float | None = None
    # True when the user allowed live checks but some could not finish, which is not a clean result.
    live_failed: bool = False
    signs: list[LinkSign] = Field(default_factory=list)
    results_file: str
    limitations: list[str] = Field(default_factory=list)


class CrossModalConflict(BaseModel):
    # Two of caption, ocr and speech.
    channels: list[str]
    kind: str
    # "conflict" means they cannot both stand as written. "note" means they differ but need not be wrong.
    severity: str
    explanation: str
    # From the submission or the media, so show them as plain text.
    left_quote: str | None = None
    right_quote: str | None = None


class ImageCaptionCheck(BaseModel):
    status: ModuleStatus
    reason: str | None = None
    score: float | None = None


class CrossModalAnalysis(BaseModel):
    status: ModuleStatus
    reason: str | None = None
    # conflicts_found, notes_only or none_found, and null when nothing could be compared.
    assessment: str | None = None
    channels: list[str] = Field(default_factory=list)
    conflicts: list[CrossModalConflict] = Field(default_factory=list)
    image_caption: ImageCaptionCheck
    limitations: list[str] = Field(default_factory=list)


class RiskComponent(BaseModel):
    name: str
    label: str
    status: ModuleStatus
    # Only measured signals are counted in the score. The rest are shown with a note saying why not.
    counted: bool
    # True when this stops the overall level reading Low, as it needs a person's review.
    blocks_low: bool = False
    score: float | None = Field(default=None, ge=0, le=1)
    weight: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    note: str | None = None
    results_file: str | None = None


class MediaDecision(BaseModel):
    """What the detectors and the web search each concluded, and how they were combined."""

    detector_verdict: str
    detector_detail: str
    web_verdict: str
    web_detail: str
    combined: str


class UnifiedRisk(BaseModel):
    level: RiskLevel
    # Null when nothing measured reached a result.
    score: float | None = None
    # At most 50, because no check can show content is genuine. Null means no score, never 0.
    trust_score: float | None = None
    trust_note: str
    reason: str | None = None
    components: list[RiskComponent] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    media_decision: MediaDecision | None = None
    # The vote and web evidence behind this result, so a report can show the working.
    calculation: dict[str, Any] = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    text: str | None = Field(default=None, max_length=20_000)
    url: HttpUrl | None = None
    # Sends the text and link to outside services and opens the link, so it is off by default.
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
    # Null when no link was submitted, and for cases saved before this field existed.
    link_analysis: LinkAnalysis | None = None
    # Null when no media was submitted, and for cases saved before this field existed.
    cross_modal: CrossModalAnalysis | None = None
    # Null for cases saved before this field existed.
    unified_risk: UnifiedRisk | None = None
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


class RelatedMediaCase(BaseModel):
    case_id: str
    # exact_copy is the same file. likely_same_image is the same picture, possibly changed.
    # shares_visible_content can be a heavy crop of one picture, or two pictures sharing something like a logo.
    kind: str
    first_seen: str | None = None
    # The case this one matched. Null means it matched the requested case itself.
    through_case_id: str | None = None
    links_from_start: int = 1
    distances: dict[str, int] = Field(default_factory=dict)
    agreeing_features: int | None = None


class RelatedMediaEvent(BaseModel):
    at: str | None = None
    # submitted, public_post or web_page.
    kind: str
    case_id: str
    label: str
    platform: str | None = None
    url: str | None = None
    matched_on: str | None = None
    date_source: str | None = None
    synthetic: bool = False
    # The earliest real item among these results, not shown to be the source.
    earliest_found: bool = False


class RelatedMediaResponse(BaseModel):
    case_id: str
    # complete, or not_applicable when this case has no saved fingerprints.
    status: str
    reason: str | None = None
    compared_cases: int = 0
    cases: list[RelatedMediaCase] = Field(default_factory=list)
    history: list[RelatedMediaEvent] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ExplanationArtifact(BaseModel):
    kind: str
    label: str = "Supporting evidence"
    url: str | None = None
    route: str | None = None
    # What was read from the file, such as speech. Untrusted, so it is only ever shown as text.
    text: str | None = None
    start_s: str | None = None

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
            "speech_segment": "Speech",
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
