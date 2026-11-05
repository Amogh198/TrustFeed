import os
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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
from backend.text.analysis import analyze_text, analyze_url, fuse_risk, signal_summary

app = FastAPI(title="TrustTrace AI API", version="0.1.0")
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


@app.post("/api/cases/analyze", response_model=AnalysisResponse)
def analyze_case(request: AnalyzeRequest) -> AnalysisResponse:
    text_result = analyze_text(request.text)[0] if request.text else None
    url_result = analyze_url(str(request.url)) if request.url else None
    modules = {
        "text": text_result or ModuleResult(
            status=ModuleStatus.NOT_APPLICABLE,
            limitations=["No text was submitted."],
        ),
        "url": url_result or ModuleResult(
            status=ModuleStatus.NOT_APPLICABLE,
            limitations=["No URL was submitted."],
        ),
        "media": ModuleResult(
            status=ModuleStatus.UNAVAILABLE,
            limitations=["Media analysis is not integrated yet."],
        ),
        "network": ModuleResult(
            status=ModuleStatus.UNAVAILABLE,
            limitations=["Network analysis is not integrated yet."],
        ),
    }
    risk = fuse_risk(text_result, url_result)
    case_id = str(uuid4())
    result = AnalysisResponse(
        case_id=case_id,
        overall_risk=risk,
        summary=signal_summary(risk),
        modules=modules,
        uncertainties=[
            "Text and URL scores are deterministic heuristics, not calibrated probabilities.",
            "No external fact-checking or domain reputation source was queried.",
        ],
        recommended_actions=["Verify factual claims with trusted sources before sharing."],
    )
    CASES[case_id] = result
    return result


@app.get("/api/cases/{case_id}", response_model=AnalysisResponse)
def get_case(case_id: str) -> AnalysisResponse:
    result = CASES.get(case_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Case not found in this server process")
    return result


@app.get("/api/network/{case_id}")
def get_network(case_id: str) -> dict[str, list[dict[str, object]]]:
    if case_id not in CASES:
        raise HTTPException(status_code=404, detail="Case not found in this server process")
    return {"nodes": [], "edges": [], "timeline": []}


@app.post("/api/cases/{case_id}/action-packet", response_model=ActionPacketResponse)
def action_packet(case_id: str, request: ActionPacketRequest) -> ActionPacketResponse:
    case = CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found in this server process")
    return ActionPacketResponse(
        case_id=case_id,
        draft=(
            f"Public information note for {request.audience}: this content has not been independently verified. "
            "Please check the cited evidence and consult trusted sources before acting or sharing."
        ),
        evidence_references=[item for module in case.modules.values() for item in module.evidence],
    )
