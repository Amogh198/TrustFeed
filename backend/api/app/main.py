import logging
import os
import shutil
import tempfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import HttpUrl

from backend.api.app.claim_records import build_claims
from backend.api.app.fusion import combine_risks, fused_summary, media_risk
from backend.api.app.models import (
    ActionPacketRequest,
    ActionPacketResponse,
    ActionPacketSection,
    AnalysisResponse,
    AnalyzeRequest,
    CaseHistoryResponse,
    HealthResponse,
    ModuleResult,
    ModuleStatus,
    ReplayScenariosResponse,
    RiskLevel,
    TimelineEvent,
    TimelineResponse,
)
from backend.api.app.replay import get_scenario, list_scenarios
from backend.api.app.store import default_store
from backend.media import MediaConfig, analyze_media
from backend.media.models import Assessment, MediaAnalysisResult
from backend.network import (
    DEMO_CASE_ID,
    get_network_clusters,
    get_network_coverage,
    get_network_module_result,
    get_network_payload,
    trace_case,
)
from backend.network.story import is_demo_story
from backend.provenance import (
    ProvenanceReport,
    get_demo_provenance,
    investigate_provenance,
)
from backend.provenance.models import MatchType, Status
from backend.text.analysis import analyze_text, analyze_url, fuse_risk, signal_summary

# Never log submitted text, links or file names: they can reveal what a user submitted.
logger = logging.getLogger(__name__)

MEDIA_UPLOAD_PATH = "/api/cases/analyze-media"
NO_EXTERNAL_CHECK = "No external fact-checking or domain reputation source was queried."
# Each link costs a search on each platform, and the trace has a 25-second budget.
MAX_TRACED_PAGE_LINKS = 10
# The largest accepted file plus room for the other form fields. analyze_media
# applies the exact limit for each media type.
MAX_UPLOAD_BYTES = MediaConfig().max_video_bytes + 1024 * 1024
# Bad uploads are the client's to fix. Other failures, such as a missing package,
# become an "unavailable" media module instead.
MEDIA_REJECTION_STATUS = {
    "too_large": 413,
    "unsupported_type": 415,
    "empty_file": 422,
    "corrupt_media": 422,
}

app = FastAPI(title="TrustTrace AI API", version="0.1.0")


def _upload_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": {"code": code, "message": message}})


# Registered before CORS so that these errors still carry CORS headers. The form
# parser spools the whole body to disk, so the size has to be checked before it runs.
@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    if request.method == "POST" and request.url.path == MEDIA_UPLOAD_PATH:
        length = request.headers.get("content-length", "")
        if not length.isdigit():
            return _upload_error(411, "length_required", "Uploads must declare a Content-Length.")
        if int(length) > MAX_UPLOAD_BYTES:
            return _upload_error(413, "too_large", "The upload exceeds the size limit.")
    return await call_next(request)


cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Hackathon starter storage: process-local and intentionally non-persistent.
CASES: dict[str, AnalysisResponse] = {}
CASE_STORE = default_store()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


def _not_applicable(reason: str) -> ModuleResult:
    return ModuleResult(status=ModuleStatus.NOT_APPLICABLE, limitations=[reason])


def _network_detail(case_id: str) -> dict[str, Any] | None:
    """Return a case's network data, from this process's trace or from the case store."""
    payload = get_network_payload(case_id)
    if payload is not None:
        return {"payload": payload, "coverage": get_network_coverage(case_id)}
    return CASE_STORE.get_detail(case_id, "network")


def _traceable_links(provenance: ProvenanceReport | None) -> tuple[str, ...]:
    """Pick pages holding this image. A merely similar picture would trace something else."""
    if provenance is None:
        return ()
    links = [
        item.page_url
        for item in provenance.appearances
        if item.page_url and item.match_type is not MatchType.SIMILAR
    ]
    return tuple(dict.fromkeys(links))[:MAX_TRACED_PAGE_LINKS]


def _trace_spread(
    case_id: str, text: str | None, url: str | None, provenance: ProvenanceReport | None = None
) -> ModuleResult:
    """Search public platforms. This sends the text and links out, so the user must opt in first."""
    if provenance is not None and provenance.replay and not is_demo_story(text, url):
        return ModuleResult(
            status=ModuleStatus.UNAVAILABLE,
            limitations=["Replay mode stays offline, so no public platform was searched."],
        )
    links = _traceable_links(provenance)
    try:
        module = ModuleResult.model_validate(trace_case(case_id, text=text, url=url, urls=links))
    except Exception as exc:  # noqa: BLE001 - A failed trace must not lose the rest of the case.
        logger.warning("Public-post trace failed: %s", type(exc).__name__)
        return ModuleResult(
            status=ModuleStatus.UNAVAILABLE,
            limitations=["The public-post trace failed unexpectedly, so no result is available."],
        )
    if links:
        module.limitations.append(
            f"The search included {len(links)} pages where the source search found this image. "
            "A post linking to one of those pages may be about something else on the page."
        )
    return module


def _store_case(
    text_result: ModuleResult | None,
    url_result: ModuleResult | None,
    media: MediaAnalysisResult | None = None,
    claims: list[str] | None = None,
    replay_label: str | None = None,
    *,
    case_id: str | None = None,
    provenance: ProvenanceReport | None = None,
    network: ModuleResult | None = None,
) -> AnalysisResponse:
    """Build and save a case. ``network`` is given only when the user asked for a trace."""
    if media is None:
        risk = fuse_risk(text_result, url_result)
        summary = signal_summary(risk)
    else:
        levels = [media_risk(media)]
        if text_result or url_result:
            levels.append(fuse_risk(text_result, url_result))
        risk = combine_risks(levels)
        summary = fused_summary(risk)

    uncertainties = [NO_EXTERNAL_CHECK]
    if text_result or url_result:
        uncertainties.insert(0, "Text and URL scores are deterministic heuristics, not calibrated probabilities.")
    recommended_actions = ["Verify factual claims with trusted sources before sharing."]
    if media is not None:
        uncertainties.append(media.summary)
        if media.assessment is Assessment.SIGNALS_PRESENT:
            recommended_actions.append("Have a person review the media before acting on this result.")
    if replay_label:
        uncertainties.append(replay_label)

    case_id = case_id or str(uuid4())
    network_detail = _network_detail(case_id) if network is not None else None
    if network is not None:
        uncertainties.append(
            "The source search and public-post trace show where content was found. "
            "They do not change the overall risk level."
        )
    if network_detail and (network_detail["coverage"] or {}).get("synthetic"):
        uncertainties.append("The public posts in this case are a labelled synthetic replay, not real activity.")
    if provenance is not None and provenance.replay:
        uncertainties.append("The source search results in this case were replayed from a recording.")

    # A trace is only given when the user allowed outside search, so the same consent covers this.
    # The labelled demo story replays offline, so it must not reach any outside service.
    synthetic_replay = bool(network_detail and (network_detail["coverage"] or {}).get("synthetic"))
    claim_records, claim_analysis = build_claims(claims or [], search_web=network is not None and not synthetic_replay)
    if claim_analysis and synthetic_replay:
        claim_analysis.verification.reason = "This labelled synthetic replay stays offline, so no claim was sent anywhere."
    if claim_analysis and claim_analysis.verification.comparison_status is ModuleStatus.COMPLETE:
        uncertainties[uncertainties.index(NO_EXTERNAL_CHECK)] = (
            "Claim results come from comparing public sources by model. They are signals, not proof. "
            "No domain reputation source was queried."
        )
    if text_result and claim_analysis:
        # Shown as evidence, but not scored: the unified risk step decides what counts.
        text_result.evidence.extend(
            f"Possible inconsistency between statements: {item.explanation}"
            for item in claim_analysis.inconsistencies
        )

    result = AnalysisResponse(
        case_id=case_id,
        overall_risk=risk,
        summary=summary,
        modules={
            "text": text_result or _not_applicable("No text was submitted."),
            "url": url_result or _not_applicable("No URL was submitted."),
            "media": (
                ModuleResult(**media.to_module_result()) if media else _not_applicable("No media was submitted.")
            ),
            "provenance": (
                ModuleResult(**provenance.to_module_result())
                if provenance
                else _not_applicable("No media was submitted, so no source search ran.")
            ),
            # The demo network describes invented accounts, so it is never attached to a submission.
            "network": network
            or ModuleResult(
                status=ModuleStatus.UNAVAILABLE,
                limitations=["No public-post trace was requested, so nothing was sent to outside platforms."],
            ),
        },
        claims=claim_records,
        claim_analysis=claim_analysis,
        uncertainties=uncertainties,
        recommended_actions=recommended_actions,
        is_replay=replay_label is not None,
        replay_label=replay_label,
    )
    CASES[case_id] = result
    CASE_STORE.save(result)
    if provenance is not None:
        CASE_STORE.save_detail(case_id, "provenance", provenance.for_case(case_id).model_dump(mode="json"))
    if network_detail is not None:
        CASE_STORE.save_detail(case_id, "network", network_detail)
    return result


@lru_cache(maxsize=1)
def _demo_case() -> AnalysisResponse:
    flagged = [
        cluster for cluster in (get_network_clusters(DEMO_CASE_ID) or []) if cluster["flagged"]
    ]
    risk = combine_risks(RiskLevel(cluster["risk_level"]) for cluster in flagged)
    reason = "The synthetic demo case has only network and source search data."
    network_module = get_network_module_result(DEMO_CASE_ID)
    demo_provenance = get_demo_provenance(DEMO_CASE_ID)
    return AnalysisResponse(
        case_id=DEMO_CASE_ID,
        overall_risk=risk,
        summary=(
            f"Synthetic demo data shows {risk.value} coordination risk. "
            "This describes how content spread, not whether it is true."
        ),
        modules={
            "text": _not_applicable(reason),
            "url": _not_applicable(reason),
            "media": _not_applicable(reason),
            "provenance": (
                ModuleResult(**demo_provenance.to_module_result())
                if demo_provenance is not None
                else _not_applicable("No synthetic source search is available.")
            ),
            "network": (
                ModuleResult.model_validate(network_module)
                if network_module is not None
                else _not_applicable("No synthetic network data is available.")
            ),
        },
        uncertainties=["All accounts and posts in this case are simulated."],
        recommended_actions=["Treat this as a demonstration; it makes no claim about real people or content."],
    )


def _find_case(case_id: str) -> AnalysisResponse:
    if case_id == DEMO_CASE_ID:
        return _demo_case()
    case = CASES.get(case_id) or CASE_STORE.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found in this server process")
    return case


def _provenance_report(case_id: str) -> ProvenanceReport:
    _find_case(case_id)
    if case_id == DEMO_CASE_ID:
        report = get_demo_provenance(DEMO_CASE_ID)
    else:
        saved = CASE_STORE.get_detail(case_id, "provenance")
        report = ProvenanceReport.model_validate(saved) if saved else None
    return report or ProvenanceReport(
        case_id=case_id,
        status=Status.NOT_APPLICABLE,
        limitations=["No source search is saved for this case."],
    )


def _network_events(detail: dict[str, Any] | None) -> list[TimelineEvent]:
    if detail is None:
        return []
    events = [
        TimelineEvent(
            at=frame["start"],
            kind="cluster_activity",
            label=f"{frame['post_count']} posts carried content from a flagged co-sharing group",
            module="network",
            ref=f"frame-{frame['frame']}",
            date_source="social_post",
            synthetic=frame["synthetic"],
        )
        for frame in detail["payload"]["timeline"]
        if frame["cluster_ids"]
    ]
    coverage = detail["coverage"] or {}
    for post in coverage.get("spread", []):
        place = "Earliest matching post these searches found" if post["earliest_found"] else "Matching post found"
        events.append(
            TimelineEvent(
                at=post["posted_at"],
                kind="social_post",
                label=f"{place} on {post['platform']}",
                module="network",
                ref=f"post-{post['order']}",
                date_source="social_post",
                synthetic=coverage["synthetic"],
            )
        )
    return events


def _in_time_order(events: list[TimelineEvent]) -> list[TimelineEvent]:
    """Put dated events first, oldest first, and keep undated ones at the end."""
    dated = sorted((event for event in events if event.at), key=lambda event: datetime.fromisoformat(event.at or ""))
    return [*dated, *(event for event in events if not event.at)]


def _analyze_upload(file: UploadFile, search_web: bool) -> tuple[MediaAnalysisResult, ProvenanceReport | None]:
    """Analyze an upload from a private temporary file, which is always deleted.

    The client's file name is never used. The media lane identifies the type from
    the file's content. A rejected file gets no source search, so it never leaves
    the server.
    """
    with tempfile.NamedTemporaryFile(prefix="trustfeed-upload-", delete=False) as handle:
        path = Path(handle.name)
        try:
            shutil.copyfileobj(file.file, handle)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    try:
        media = analyze_media(path)
        if media.failure_code in MEDIA_REJECTION_STATUS:
            return media, None
        return media, investigate_provenance(path, search_web=search_web)
    finally:
        path.unlink(missing_ok=True)


@app.post("/api/cases/analyze", response_model=AnalysisResponse)
def analyze_case(request: AnalyzeRequest) -> AnalysisResponse:
    text_result, claims = analyze_text(request.text) if request.text else (None, [])
    url = str(request.url) if request.url else None
    url_result = analyze_url(url) if url else None
    if not request.search_web:
        return _store_case(text_result, url_result, claims=claims)
    case_id = str(uuid4())
    network = _trace_spread(case_id, request.text if text_result else None, url)
    return _store_case(text_result, url_result, claims=claims, case_id=case_id, network=network)


@app.post(MEDIA_UPLOAD_PATH, response_model=AnalysisResponse)
def analyze_media_case(
    file: Annotated[UploadFile, File(description="JPEG, PNG, WebP, MP4, MOV, WebM or AVI.")],
    text: Annotated[str | None, Form(max_length=20_000)] = None,
    url: Annotated[HttpUrl | None, Form()] = None,
    search_web: Annotated[bool, Form(description="Allow sending the image, text and link to outside services.")] = False,
) -> AnalysisResponse:
    media, provenance = _analyze_upload(file, search_web)
    rejection = MEDIA_REJECTION_STATUS.get(media.failure_code or "")
    if rejection is not None:
        raise HTTPException(
            status_code=rejection,
            detail={"code": media.failure_code, "message": media.limitations[0]},
        )
    text_result, claims = analyze_text(text) if text and text.strip() else (None, [])
    link = str(url) if url else None
    url_result = analyze_url(link) if link else None
    if not search_web:
        return _store_case(text_result, url_result, media, claims, provenance=provenance)
    case_id = str(uuid4())
    network = _trace_spread(case_id, text if text_result else None, link, provenance)
    return _store_case(text_result, url_result, media, claims, case_id=case_id, provenance=provenance, network=network)


@app.get("/api/cases", response_model=CaseHistoryResponse)
def list_cases(
    limit: int = Query(default=25, ge=1, le=100),
    risk_level: RiskLevel | None = None,
) -> CaseHistoryResponse:
    cases, total = CASE_STORE.list(limit=limit, risk_level=risk_level)
    return CaseHistoryResponse(cases=cases, total=total)


@app.get("/api/replay/scenarios", response_model=ReplayScenariosResponse)
def replay_scenarios() -> ReplayScenariosResponse:
    return ReplayScenariosResponse(scenarios=list_scenarios())


@app.post("/api/replay/{scenario_id}/start", response_model=AnalysisResponse)
def start_replay(scenario_id: str) -> AnalysisResponse:
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Replay scenario not found")
    text_result, claims = analyze_text(scenario.text)
    url_result = analyze_url(str(scenario.url)) if scenario.url else None
    return _store_case(text_result, url_result, claims=claims, replay_label=scenario.label)


@app.get("/api/cases/{case_id}/export", response_model=AnalysisResponse)
def export_case(case_id: str) -> AnalysisResponse:
    """Return the stored report as JSON for offline export or presentation."""
    return _find_case(case_id)


@app.get("/api/cases/{case_id}", response_model=AnalysisResponse)
def get_case(case_id: str) -> AnalysisResponse:
    return _find_case(case_id)


@app.get("/api/cases/{case_id}/provenance", response_model=ProvenanceReport)
def get_provenance(case_id: str) -> ProvenanceReport:
    return _provenance_report(case_id)


@app.get("/api/cases/{case_id}/timeline", response_model=TimelineResponse)
def get_timeline(case_id: str) -> TimelineResponse:
    report = _provenance_report(case_id)
    events = [TimelineEvent.model_validate(event) for event in report.timeline_events()]
    return TimelineResponse(events=_in_time_order([*events, *_network_events(_network_detail(case_id))]))


@app.get("/api/network/{case_id}")
def get_network(case_id: str) -> dict[str, list[dict[str, object]]]:
    detail = _network_detail(case_id)
    if detail is not None:
        return detail["payload"]
    _find_case(case_id)
    return {"nodes": [], "edges": [], "timeline": []}


@app.get("/api/network/{case_id}/coverage")
def get_coverage(case_id: str) -> dict[str, object] | None:
    """Say what a trace searched and missed. Null means no trace ran for this case."""
    detail = _network_detail(case_id)
    if detail is None:
        _find_case(case_id)
        return None
    return detail["coverage"]


@app.post("/api/cases/{case_id}/action-packet", response_model=ActionPacketResponse)
def action_packet(case_id: str, request: ActionPacketRequest) -> ActionPacketResponse:
    case = _find_case(case_id)
    evidence = [item for module in case.modules.values() for item in module.evidence]
    sections = [
        ActionPacketSection(
            heading="Assessment",
            items=[case.summary, f"Risk level: {case.overall_risk.value}. This is a triage signal, not a factual verdict."],
        ),
        ActionPacketSection(
            heading="Evidence observed",
            items=evidence or ["No module produced evidence for this case."],
        ),
        ActionPacketSection(
            heading="Claim status",
            items=(
                [f"{claim.text} — {claim.verdict.value}; {claim.rationale}" for claim in case.claims]
                or ["No text claim was supplied for atomization."]
            ),
        ),
        ActionPacketSection(heading="Uncertainties", items=case.uncertainties or ["No additional uncertainty was recorded."]),
        ActionPacketSection(heading="Recommended next actions", items=case.recommended_actions),
    ]
    draft_lines = [
        f"TruthTrace AI draft for {request.audience}.",
        "This template is assembled from the case record; no generative model or external fact-check was used.",
    ]
    for section in sections:
        draft_lines.append(f"\n{section.heading}:")
        draft_lines.extend(f"- {item}" for item in section.items)
    return ActionPacketResponse(
        case_id=case_id,
        label="Evidence-based template only; no generative model or external verification was used.",
        draft="\n".join(draft_lines),
        evidence_references=evidence,
        sections=sections,
    )
