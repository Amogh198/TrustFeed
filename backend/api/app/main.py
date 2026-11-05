import os
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import HttpUrl

from backend.api.app.fusion import combine_risks, fused_summary, media_risk
from backend.api.app.models import (
    ActionPacketRequest,
    ActionPacketResponse,
    AnalysisResponse,
    AnalyzeRequest,
    HealthResponse,
    ModuleResult,
    ModuleStatus,
    RiskLevel,
)
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


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


def _not_applicable(reason: str) -> ModuleResult:
    return ModuleResult(status=ModuleStatus.NOT_APPLICABLE, limitations=[reason])


def _store_case(
    text_result: ModuleResult | None,
    url_result: ModuleResult | None,
    media: MediaAnalysisResult | None = None,
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
        uncertainties=uncertainties,
        recommended_actions=recommended_actions,
    )
    CASES[case_id] = result
    return result


@lru_cache(maxsize=1)
def _demo_case() -> AnalysisResponse:
    flagged = [cluster for cluster in get_network_clusters(DEMO_CASE_ID) if cluster["flagged"]]
    risk = combine_risks(RiskLevel(cluster["risk_level"]) for cluster in flagged)
    reason = "The synthetic demo case has only network data."
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
            "network": ModuleResult(**get_network_module_result(DEMO_CASE_ID)),
        },
        uncertainties=["All accounts and posts in this case are simulated."],
        recommended_actions=["Treat this as a demonstration; it makes no claim about real people or content."],
    )


def _find_case(case_id: str) -> AnalysisResponse:
    if case_id == DEMO_CASE_ID:
        return _demo_case()
    case = CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found in this server process")
    return case


def _analyze_upload(file: UploadFile) -> MediaAnalysisResult:
    """Analyze an upload from a private temporary file, which is always deleted.

    The client's file name is never used. The media lane identifies the type from
    the file's content.
    """
    handle = tempfile.NamedTemporaryFile(prefix="trustfeed-upload-", delete=False)
    path = Path(handle.name)
    try:
        with handle:
            shutil.copyfileobj(file.file, handle)
        return analyze_media(path)
    finally:
        path.unlink(missing_ok=True)


@app.post("/api/cases/analyze", response_model=AnalysisResponse)
def analyze_case(request: AnalyzeRequest) -> AnalysisResponse:
    text_result = analyze_text(request.text)[0] if request.text else None
    url_result = analyze_url(str(request.url)) if request.url else None
    return _store_case(text_result, url_result)


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
    text_result = analyze_text(text)[0] if text and text.strip() else None
    url_result = analyze_url(str(url)) if url else None
    return _store_case(text_result, url_result, media)


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
    return ActionPacketResponse(
        case_id=case_id,
        draft=(
            f"Public information note for {request.audience}: this content has not been independently verified. "
            "Please check the cited evidence and consult trusted sources before acting or sharing."
        ),
        evidence_references=[item for module in case.modules.values() for item in module.evidence],
    )
