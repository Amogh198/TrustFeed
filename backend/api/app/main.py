import os
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import HttpUrl

from backend.api.app.fusion import combine_risks, fused_summary, media_risk
from backend.api.app.models import (
    ActionPacketRequest,
    ActionPacketResponse,
    ActionPacketSection,
    AnalysisResponse,
    AnalyzeRequest,
    CaseHistoryResponse,
    ClaimRecord,
    HealthResponse,
    ModuleResult,
    ModuleStatus,
    ReplayScenariosResponse,
    RiskLevel,
)
from backend.api.app.replay import get_scenario, list_scenarios
from backend.api.app.store import default_store
from backend.media import MediaConfig, analyze_media
from backend.media.models import Assessment, MediaAnalysisResult
from backend.network import (
    DEMO_CASE_ID,
    get_network_clusters,
    get_network_module_result,
    get_network_payload,
)
from backend.text.analysis import analyze_text, analyze_url, fuse_risk, signal_summary

MEDIA_UPLOAD_PATH = "/api/cases/analyze-media"
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


def _store_case(
    text_result: ModuleResult | None,
    url_result: ModuleResult | None,
    media: MediaAnalysisResult | None = None,
    claims: list[str] | None = None,
    replay_label: str | None = None,
) -> AnalysisResponse:
    if media is None:
        risk = fuse_risk(text_result, url_result)
        summary = signal_summary(risk)
    else:
        levels = [media_risk(media)]
        if text_result or url_result:
            levels.append(fuse_risk(text_result, url_result))
        risk = combine_risks(levels)
        summary = fused_summary(risk)

    uncertainties = ["No external fact-checking or domain reputation source was queried."]
    if text_result or url_result:
        uncertainties.insert(0, "Text and URL scores are deterministic heuristics, not calibrated probabilities.")
    recommended_actions = ["Verify factual claims with trusted sources before sharing."]
    if media is not None:
        uncertainties.append(media.summary)
        if media.assessment is Assessment.SIGNALS_PRESENT:
            recommended_actions.append("Have a person review the media before acting on this result.")
    if replay_label:
        uncertainties.append(replay_label)

    case_id = str(uuid4())
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
            # The demo network describes invented accounts, so it is never attached to a submission.
            "network": ModuleResult(
                status=ModuleStatus.UNAVAILABLE,
                limitations=["No dissemination data exists for this submission, so network analysis did not run."],
            ),
        },
        claims=[ClaimRecord(id=f"claim-{index}", text=claim) for index, claim in enumerate(claims or [], start=1)],
        uncertainties=uncertainties,
        recommended_actions=recommended_actions,
        is_replay=replay_label is not None,
        replay_label=replay_label,
    )
    CASES[case_id] = result
    CASE_STORE.save(result)
    return result


@lru_cache(maxsize=1)
def _demo_case() -> AnalysisResponse:
    flagged = [
        cluster for cluster in (get_network_clusters(DEMO_CASE_ID) or []) if cluster["flagged"]
    ]
    risk = combine_risks(RiskLevel(cluster["risk_level"]) for cluster in flagged)
    reason = "The synthetic demo case has only network data."
    network_module = get_network_module_result(DEMO_CASE_ID)
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


def _analyze_upload(file: UploadFile) -> MediaAnalysisResult:
    """Analyze an upload from a private temporary file, which is always deleted.

    The client's file name is never used. The media lane identifies the type from
    the file's content.
    """
    with tempfile.NamedTemporaryFile(prefix="trustfeed-upload-", delete=False) as handle:
        path = Path(handle.name)
        try:
            shutil.copyfileobj(file.file, handle)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    try:
        return analyze_media(path)
    finally:
        path.unlink(missing_ok=True)


@app.post("/api/cases/analyze", response_model=AnalysisResponse)
def analyze_case(request: AnalyzeRequest) -> AnalysisResponse:
    text_result, claims = analyze_text(request.text) if request.text else (None, [])
    url_result = analyze_url(str(request.url)) if request.url else None
    return _store_case(text_result, url_result, claims=claims)


@app.post(MEDIA_UPLOAD_PATH, response_model=AnalysisResponse)
def analyze_media_case(
    file: Annotated[UploadFile, File(description="JPEG, PNG, WebP, MP4, MOV, WebM or AVI.")],
    text: Annotated[str | None, Form(max_length=20_000)] = None,
    url: Annotated[HttpUrl | None, Form()] = None,
) -> AnalysisResponse:
    media = _analyze_upload(file)
    rejection = MEDIA_REJECTION_STATUS.get(media.failure_code or "")
    if rejection is not None:
        raise HTTPException(
            status_code=rejection,
            detail={"code": media.failure_code, "message": media.limitations[0]},
        )
    text_result, claims = analyze_text(text) if text and text.strip() else (None, [])
    url_result = analyze_url(str(url)) if url else None
    return _store_case(text_result, url_result, media, claims)


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


@app.get("/api/network/{case_id}")
def get_network(case_id: str) -> dict[str, list[dict[str, object]]]:
    payload = get_network_payload(case_id)
    if payload is not None:
        return payload
    _find_case(case_id)
    return {"nodes": [], "edges": [], "timeline": []}


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
