import base64
import json
import logging
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import unquote
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import HttpUrl

from backend.api.app.auth import (
    COOKIE_NAME,
    CURRENT_USER,
    AuthStore,
    auth_required,
    build_router,
    current_owner,
)
from backend.api.app.claim_records import build_claims
from backend.api.app.explanation import build_explanation
from backend.api.app.fusion import (
    action_packet as fusion_action_packet,
)
from backend.api.app.fusion import (
    combine_risks,
    disagreement_note,
    fused_summary,
    media_risk,
)
from backend.api.app.models import (
    ActionPacketRequest,
    ActionPacketResponse,
    AnalysisResponse,
    AnalyzeRequest,
    CaseHistoryResponse,
    CaseSummary,
    ClaimRecord,
    ExplanationResponse,
    HealthResponse,
    HeatmapResponse,
    LinkAnalysis,
    ModuleResult,
    ModuleStatus,
    MonitorStartRequest,
    RelatedMediaResponse,
    ReplayScenariosResponse,
    RiskLevel,
    TimelineEvent,
    TimelineResponse,
)
from backend.api.app.related_media import build_related_media
from backend.api.app.replay import get_scenario, list_scenarios
from backend.api.app.report import build_overview, build_report, case_kinds, render_pdf
from backend.api.app.risk import build_unified_risk, summary_for
from backend.api.app.scam_records import build_scam_analysis
from backend.api.app.store import default_store
from backend.media import MediaConfig, analyze_media, occlusion_heatmap, render_png
from backend.media.classifier import default_classifier
from backend.media.errors import MediaInputError
from backend.media.fingerprint import CaseFingerprint, fingerprint_record
from backend.media.metadata import inspect_input, read_image
from backend.media.models import Assessment, MediaAnalysisResult, MediaType
from backend.media.related import add_earlier_matches
from backend.network import (
    DEMO_CASE_ID,
    DEMO_STORY_CASE_ID,
    WatchError,
    build_network_checks,
    get_demo_story,
    get_network_clusters,
    get_network_coverage,
    get_network_module_result,
    get_network_payload,
    get_network_tests,
    list_watches,
    poll_watch,
    start_watch,
    stop_watch,
    trace_case,
)
from backend.network.story import is_demo_story
from backend.provenance import (
    ProvenanceReport,
    get_demo_provenance,
    investigate_provenance,
)
from backend.provenance.models import MatchType, Status
from backend.text.analysis import (
    analyze_text,
    analyze_url,
    expand_shortener,
    fuse_risk,
    signal_summary,
)
from backend.text.cross_modal import compare_channels
from backend.text.links import investigate_link
from backend.text.scams import WARNING_SIGNS

# Never log submitted text, links or file names: they can reveal what a user submitted.
logger = logging.getLogger(__name__)

MEDIA_UPLOAD_PATH = "/api/cases/analyze-media"
NO_EXTERNAL_CHECK = "No external fact-checking or domain reputation source was queried."
HEATMAP_PATH = "/api/media/heatmap"
# A heatmap takes about 65 model runs, so only one runs at a time.
_heatmap_slot = threading.Lock()
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

app = FastAPI(title="TrustFeed API", version="0.1.0")


def _upload_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": {"code": code, "message": message}})


# Registered before CORS so that these errors still carry CORS headers. The form
# parser spools the whole body to disk, so the size has to be checked before it runs.
@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    if request.method == "POST" and request.url.path in (MEDIA_UPLOAD_PATH, "/api/cases/media", HEATMAP_PATH):
        length = request.headers.get("content-length", "")
        if not length.isdigit():
            return _upload_error(411, "length_required", "Uploads must declare a Content-Length.")
        if int(length) > MAX_UPLOAD_BYTES:
            return _upload_error(413, "too_large", "The upload exceeds the size limit.")
    return await call_next(request)


CASE_NOT_FOUND = "Case not found in this server process"
cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
_CASE_PATH = re.compile(r"^/api/(?:cases|network)/([^/]+)")
_OPEN_WHEN_REQUIRED = ("/health", "/api/auth/")


@app.middleware("http")
async def accounts(request: Request, call_next):
    """Decide who is asking, and refuse what they can't see, before any route runs.

    Checking here means a route added under a case's path is covered without further work.
    """
    token = request.cookies.get(COOKIE_NAME)
    origin = request.headers.get("origin")
    changes = request.method in ("POST", "PUT", "PATCH", "DELETE")
    # A browser marks where a request came from, so a page on another site can't act as the user.
    if changes and origin and origin not in cors_origins and (token or request.url.path.startswith("/api/auth/")):
        return JSONResponse(status_code=403, content={"detail": "This request came from a site this server doesn't trust."})
    user = await run_in_threadpool(AUTH_STORE.user_for_token, token)
    if (
        auth_required()
        and user is None
        and request.method != "OPTIONS"
        and not request.url.path.startswith(_OPEN_WHEN_REQUIRED)
    ):
        return JSONResponse(status_code=401, content={"detail": "Sign in to use this server."})
    found = _CASE_PATH.match(request.url.path)
    if found:
        saved, owner = await run_in_threadpool(CASE_STORE.owner_of, unquote(found.group(1)))
        if saved and owner is not None and (user is None or user.id != owner):
            # The same answer as a case that doesn't exist, so an ID can't be probed.
            return JSONResponse(status_code=404, content={"detail": CASE_NOT_FOUND})
    CURRENT_USER.set(user)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

# Hackathon starter storage: process-local and intentionally non-persistent.
CASES: dict[str, AnalysisResponse] = {}
CASE_STORE = default_store()
AUTH_STORE = AuthStore(CASE_STORE.path)
# Added one by one, because tools/compat_check.py reads each route's path from app.routes.
app.router.routes.extend(build_router(AUTH_STORE).routes)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


def _not_applicable(reason: str) -> ModuleResult:
    return ModuleResult(status=ModuleStatus.NOT_APPLICABLE, limitations=[reason])


def _network_detail(case_id: str) -> dict[str, Any] | None:
    """Return a case's network data, from this process's trace or from the case store."""
    payload = get_network_payload(case_id)
    if payload is not None:
        return {"payload": payload, "coverage": get_network_coverage(case_id), "tests": get_network_tests(case_id)}
    return CASE_STORE.get_detail(case_id, "network")


def _replay_mode() -> bool:
    """Replay mode promises to stay offline, so it stops every outside request."""
    return bool(os.getenv("PROVENANCE_REPLAY_PATH"))


def _follow_short_link(url: str | None) -> str | None:
    return expand_shortener(url) if url and not _replay_mode() else None


LINK_CHECK_LIMIT_SECONDS = 30.0
MAX_SEARCHED_CASES = 500


def _check_link(url: str | None, search_web: bool, text: str | None = None) -> LinkAnalysis | None:
    """Look into a link. Opening it or asking a registry about it needs the user's consent."""
    if not url:
        return None
    if not search_web:
        return investigate_link(url, offline_reason="Not checked, because outside requests were not allowed.")
    if _replay_mode() or is_demo_story(text, url):
        return investigate_link(url, offline_reason="Replay stays offline, so this was not checked.")
    # Run apart with a hard limit, as a site sending its headers very slowly can outlast the request timeouts.
    box: dict[str, LinkAnalysis] = {}

    def work() -> None:
        try:
            box["report"] = investigate_link(url)
        except Exception as exc:  # noqa: BLE001 - A failed check must not lose the rest of the case.
            logger.warning("Link check failed: %s", type(exc).__name__)

    worker = threading.Thread(target=work, daemon=True, name="link-check")
    worker.start()
    worker.join(LINK_CHECK_LIMIT_SECONDS)
    if "report" in box:
        return box["report"]
    report = investigate_link(url, offline_reason="The link check failed or ran out of time, so only the address was checked.")
    report.live_failed = True
    return report


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


def _owner_fingerprints() -> list[CaseFingerprint]:
    """Fingerprints of this owner's saved cases. Signed-out cases share one pool, as they share one case list."""
    records = []
    for detail in CASE_STORE.details_for_owner("media_fingerprints", current_owner(), MAX_SEARCHED_CASES):
        try:
            records.append(CaseFingerprint.model_validate(detail))
        except ValueError:
            continue
    return records


def _compare_with_earlier_cases(media: MediaAnalysisResult) -> None:
    """Add matches with this owner's earlier cases. A failure here must not lose the rest of the case."""
    try:
        add_earlier_matches(media, _owner_fingerprints())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Comparing with earlier cases failed: %s", type(exc).__name__)


def _submitted_hashes(media: MediaAnalysisResult | None) -> tuple[dict[str, str], ...]:
    record = fingerprint_record(media, "", "") if media else None
    return tuple(record.frames) if record else ()


def _submitted_features(media: MediaAnalysisResult | None) -> tuple[str, ...]:
    check = media.checks.fingerprint if media else None
    return tuple(check.local_features) if check else ()


def _trace_spread(
    case_id: str,
    text: str | None,
    url: str | None,
    provenance: ProvenanceReport | None = None,
    media: MediaAnalysisResult | None = None,
) -> ModuleResult:
    """Search public platforms. This sends the text and links out, so the user must opt in first."""
    replaying = _replay_mode() or (provenance is not None and provenance.replay)
    if replaying and not is_demo_story(text, url):
        return ModuleResult(
            status=ModuleStatus.UNAVAILABLE,
            limitations=["Replay mode stays offline, so no public platform was searched."],
        )
    links = _traceable_links(provenance)
    try:
        module = ModuleResult.model_validate(
            trace_case(
                case_id,
                text=text,
                url=url,
                urls=links,
                submitted_hashes=_submitted_hashes(media),
                submitted_features=_submitted_features(media),
            )
        )
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
    link_analysis: LinkAnalysis | None = None,
) -> AnalysisResponse:
    """Build and save a case. ``network`` is given only when the user asked for a trace."""
    module_levels: dict[str, RiskLevel] = {}
    if text_result:
        module_levels["the text check"] = fuse_risk(text_result, None)
    if url_result:
        module_levels["the link check"] = fuse_risk(None, url_result)
    if media is None:
        risk = fuse_risk(text_result, url_result)
        summary = signal_summary(risk)
    else:
        module_levels["the media check"] = media_risk(media)
        levels = [media_risk(media)]
        if text_result or url_result:
            levels.append(fuse_risk(text_result, url_result))
        risk = combine_risks(levels)
        summary = fused_summary(risk)

    uncertainties = [NO_EXTERNAL_CHECK]
    if text_result or url_result:
        uncertainties.insert(0, "Text and URL scores are deterministic heuristics, not calibrated probabilities.")
    disagreement = disagreement_note(module_levels)
    if disagreement:
        uncertainties.append(disagreement)
    recommended_actions = ["Verify factual claims with trusted sources before sharing."]
    if media is not None:
        uncertainties.append(media.summary)
        if media.assessment is Assessment.NO_STRONG_SIGNALS:
            uncertainties.append(
                "The media detector found no strong signal, which counts as inconclusive. "
                "It flags few fakes at its current settings, so this does not show the media is authentic."
            )
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
    scam_analysis = build_scam_analysis("\n".join(claims)) if claims else None
    if scam_analysis and text_result:
        # Shown as evidence, but not scored: the unified risk step decides what counts.
        text_result.evidence.extend(
            f"Scam warning sign ({item.category}): {item.why} Found: {item.quote!r}" for item in scam_analysis.signs
        )
    if scam_analysis and scam_analysis.assessment == WARNING_SIGNS:
        recommended_actions.append(
            "Do not pay, share a code or password, or click links in this message. Contact the organization "
            "through its official website or number."
        )
    if text_result and claim_analysis:
        # Shown as evidence, but not scored: the unified risk step decides what counts.
        text_result.evidence.extend(
            f"Possible inconsistency between statements: {item.explanation}"
            for item in claim_analysis.inconsistencies
        )

    if link_analysis and url_result:
        # Shown as evidence, but not scored: the unified risk step decides what counts.
        url_result.evidence.extend(f"Link warning sign: {item.why}" for item in link_analysis.signs)
    if link_analysis and link_analysis.assessment == WARNING_SIGNS:
        recommended_actions.append(
            "Do not open this link or enter any details. Go to the organization's official site directly instead."
        )

    cross_modal = None
    if media is not None:
        # The media check doesn't send text yet. When it does, this picks it up without a change.
        cross_modal = compare_channels(" ".join(claims or []), getattr(media, "extracted_text", None))
    if cross_modal and text_result:
        # Shown as evidence, but not scored, as this hasn't been measured.
        text_result.evidence.extend(f"Media and caption differ: {item.explanation}" for item in cross_modal.conflicts)

    media_module = ModuleResult(**media.to_module_result()) if media else None
    unified = build_unified_risk(
        text=text_result,
        url=url_result,
        media=media_module,
        media_level=media_risk(media) if media else None,
        network=network,
        claims=claim_records,
        claim_analysis=claim_analysis,
        scam_analysis=scam_analysis,
        link_analysis=link_analysis,
        cross_modal=cross_modal,
    )
    risk = unified.level
    summary = summary_for(unified)

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
        scam_analysis=scam_analysis,
        link_analysis=link_analysis,
        cross_modal=cross_modal,
        unified_risk=unified,
        uncertainties=uncertainties,
        recommended_actions=recommended_actions,
        is_replay=replay_label is not None,
        replay_label=replay_label,
    )
    CASES[case_id] = result
    CASE_STORE.save(result, owner_id=current_owner())
    if media is not None:
        # The upload is deleted, so its explanation is saved now while the result exists.
        CASE_STORE.save_detail(case_id, "media_checks", {"checks": media.to_checks()})
        record = fingerprint_record(media, case_id, result.created_at.isoformat())
        if record is not None:
            CASE_STORE.save_detail(case_id, "media_fingerprints", record.model_dump())
    if provenance is not None:
        CASE_STORE.save_detail(case_id, "provenance", provenance.for_case(case_id).model_dump(mode="json"))
    if network_detail is not None:
        CASE_STORE.save_detail(case_id, "network", network_detail)
    return result


SYNTHETIC_DEMO_LABEL = "SYNTHETIC DEMO: invented accounts and posts, not evidence of real activity."


@lru_cache(maxsize=1)
def _demo_story_case() -> AnalysisResponse:
    """Serve the linked demo story as a whole case, using its labelled offline recording."""
    submission = get_demo_story()["submission"]
    text_result, claims = analyze_text(submission["text"])
    url_result = analyze_url(submission["url"])
    risk = fuse_risk(text_result, url_result)
    network_module = get_network_module_result(DEMO_STORY_CASE_ID)
    return AnalysisResponse(
        case_id=DEMO_STORY_CASE_ID,
        is_replay=True,
        replay_label=SYNTHETIC_DEMO_LABEL,
        overall_risk=risk,
        summary=(
            f"Rule-based indicators suggest {risk.value} risk for this invented post. "
            "The trace below replays invented accounts, and shows how spread would be analyzed."
        ),
        modules={
            "text": text_result,
            "url": url_result,
            "media": _not_applicable("The demo story has no media file."),
            "provenance": _not_applicable("The demo story has no media file, so no source search ran."),
            "network": ModuleResult.model_validate(network_module),
        },
        claims=[ClaimRecord(id=f"claim-{index}", text=claim) for index, claim in enumerate(claims, start=1)],
        uncertainties=[
            "All accounts, posts and platforms in this case are invented.",
            "The earliest post found is outside the flagged group, which shows why earliest found does not mean the source.",
        ],
        recommended_actions=["Treat this as a demonstration; it makes no claim about real people or content."],
    )


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
        is_replay=True,
        replay_label=SYNTHETIC_DEMO_LABEL,
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
        uncertainties=["Synthetic demo: all accounts and posts in this case are simulated."],
        recommended_actions=["Treat this as a demonstration; it makes no claim about real people or content."],
    )


def _find_case(case_id: str) -> AnalysisResponse:
    if case_id == DEMO_CASE_ID:
        return _demo_case()
    if case_id == DEMO_STORY_CASE_ID:
        return _demo_story_case()
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


def _analyze_upload(
    file: UploadFile, search_web: bool, deep_check: bool = False
) -> tuple[MediaAnalysisResult, ProvenanceReport | None]:
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
        media = analyze_media(path, run_heavy=True) if deep_check else analyze_media(path)
        if media.failure_code in MEDIA_REJECTION_STATUS:
            return media, None
        return media, investigate_provenance(path, search_web=search_web)
    finally:
        path.unlink(missing_ok=True)


@app.post("/api/cases/analyze", response_model=AnalysisResponse)
def analyze_case(request: AnalyzeRequest) -> AnalysisResponse:
    text_result, claims = analyze_text(request.text) if request.text else (None, [])
    url = str(request.url) if request.url else None
    if not request.search_web:
        url_result = analyze_url(url) if url else None
        return _store_case(text_result, url_result, claims=claims, link_analysis=_check_link(url, False))
    destination = _follow_short_link(url)
    url_result = analyze_url(url, destination, follow_tried=not _replay_mode()) if url else None
    case_id = str(uuid4())
    network = _trace_spread(case_id, request.text if text_result else None, destination or url)
    link_analysis = _check_link(url, True, request.text if text_result else None)
    return _store_case(text_result, url_result, claims=claims, case_id=case_id, network=network, link_analysis=link_analysis)


@app.post(MEDIA_UPLOAD_PATH, response_model=AnalysisResponse)
@app.post("/api/cases/media", response_model=AnalysisResponse)
def analyze_media_case(
    file: Annotated[UploadFile, File(description="JPEG, PNG, WebP, MP4, MOV, WebM, AVI, MP3, WAV, M4A, FLAC or OGG.")],
    text: Annotated[str | None, Form(max_length=20_000)] = None,
    url: Annotated[HttpUrl | None, Form()] = None,
    search_web: Annotated[bool, Form(description="Allow sending the image, text and link to outside services.")] = False,
    deep_check: Annotated[bool, Form(description="Also run a video's speech, synthetic speech and frame checks. This can take minutes.")] = False,
) -> AnalysisResponse:
    media, provenance = _analyze_upload(file, search_web, deep_check)
    rejection = MEDIA_REJECTION_STATUS.get(media.failure_code or "")
    if rejection is not None:
        raise HTTPException(
            status_code=rejection,
            detail={"code": media.failure_code, "message": media.limitations[0]},
        )
    _compare_with_earlier_cases(media)
    text_result, claims = analyze_text(text) if text and text.strip() else (None, [])
    link = str(url) if url else None
    if not search_web:
        url_result = analyze_url(link) if link else None
        return _store_case(
            text_result, url_result, media, claims, provenance=provenance, link_analysis=_check_link(link, False)
        )
    destination = _follow_short_link(link)
    url_result = analyze_url(link, destination, follow_tried=not _replay_mode()) if link else None
    case_id = str(uuid4())
    network = _trace_spread(case_id, text if text_result else None, destination or link, provenance, media)
    link_analysis = _check_link(link, True, text if text_result else None)
    return _store_case(
        text_result, url_result, media, claims, case_id=case_id, provenance=provenance, network=network, link_analysis=link_analysis
    )


@app.get("/api/cases", response_model=CaseHistoryResponse)
def list_cases(
    limit: int = Query(default=25, ge=1, le=100),
    risk_level: RiskLevel | None = None,
    q: Annotated[str | None, Query(max_length=200, description="Words to find in a saved report.")] = None,
    kind: Annotated[Literal["media", "link", "text", "scam", "campaign"] | None, Query()] = None,
) -> CaseHistoryResponse:
    if not q and not kind:
        cases, total = CASE_STORE.list(limit=limit, risk_level=risk_level, owner_id=current_owner())
        return CaseHistoryResponse(cases=cases, total=total)
    # Only the newest reports are searched, which keeps this quick on a local database.
    found = []
    needle = (q or "").casefold()
    for case in CASE_STORE.recent(MAX_SEARCHED_CASES, current_owner()):
        if risk_level and case.overall_risk is not risk_level:
            continue
        if kind and kind not in case_kinds(case):
            continue
        if needle and needle not in case.model_dump_json().casefold():
            continue
        found.append(CaseSummary(**case.model_dump(include=set(CaseSummary.model_fields))))
    return CaseHistoryResponse(cases=found[:limit], total=len(found))


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    """Counts across saved reports, from their stored results."""
    owner = current_owner()
    return build_overview(CASE_STORE.recent(MAX_SEARCHED_CASES, owner), CASE_STORE.list(limit=1, owner_id=owner)[1])


@app.get("/api/replay/scenarios", response_model=ReplayScenariosResponse)
def replay_scenarios() -> ReplayScenariosResponse:
    return ReplayScenariosResponse(scenarios=list_scenarios())


@app.post("/api/replay/{scenario_id}/start", response_model=AnalysisResponse)
def start_replay(scenario_id: str) -> AnalysisResponse:
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Replay scenario not found")
    text_result, claims = analyze_text(scenario.text)
    link = str(scenario.url) if scenario.url else None
    url_result = analyze_url(link) if link else None
    link_analysis = investigate_link(link, offline_reason="Replay stays offline, so this was not checked.") if link else None
    return _store_case(text_result, url_result, claims=claims, replay_label=scenario.label, link_analysis=link_analysis)


@app.get("/api/cases/{case_id}/export", response_model=AnalysisResponse)
def export_case(case_id: str) -> AnalysisResponse:
    """Return the stored report as JSON for offline export or presentation."""
    return _find_case(case_id)


@app.get("/api/cases/{case_id}", response_model=AnalysisResponse)
def get_case(case_id: str) -> AnalysisResponse:
    return _find_case(case_id)


def _report(case_id: str) -> dict[str, Any]:
    case = _find_case(case_id)
    return build_report(case, CASE_STORE.get_detail(case_id, "provenance"), _network_detail(case_id))


@app.get("/api/cases/{case_id}/report")
def get_report(case_id: str) -> dict[str, Any]:
    return _report(case_id)


@app.get("/api/cases/{case_id}/report.pdf")
def get_report_pdf(case_id: str) -> Response:
    # The name comes from the stored ID, never from the request, as _find_case has matched it.
    name = f"trustfeed-report-{_find_case(case_id).case_id[:8]}.pdf"
    return Response(
        render_pdf(_report(case_id)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/api/cases/{case_id}/provenance", response_model=ProvenanceReport)
def get_provenance(case_id: str) -> ProvenanceReport:
    return _provenance_report(case_id)


@app.get("/api/cases/{case_id}/timeline", response_model=TimelineResponse)
def get_timeline(case_id: str) -> TimelineResponse:
    report = _provenance_report(case_id)
    events = [TimelineEvent.model_validate(event) for event in report.timeline_events()]
    return TimelineResponse(events=_in_time_order([*events, *_network_events(_network_detail(case_id))]))


@app.get("/api/cases/{case_id}/related-media", response_model=RelatedMediaResponse)
def get_related_media(case_id: str) -> RelatedMediaResponse:
    """Other cases on this account holding the same picture, and what each one found, as one history."""
    _find_case(case_id)
    return build_related_media(case_id, _owner_fingerprints(), CASE_STORE.get_detail, _network_detail)


@app.get("/api/cases/{case_id}/explanation", response_model=ExplanationResponse)
def get_explanation(case_id: str) -> ExplanationResponse:
    """Explain every check from what was really run. Anything not run is listed as missing."""
    case = _find_case(case_id)
    media_detail = CASE_STORE.get_detail(case_id, "media_checks") or {}
    report = _provenance_report(case_id)
    provenance_checks = report.to_checks() if report.status is not Status.NOT_APPLICABLE else []
    if provenance_checks:
        # Keep the old aggregate check ID available while clients move to the
        # detailed provenance.search and provenance.similar checks.
        search = provenance_checks[0]
        provenance_checks.append({
            "check_id": "provenance-search",
            "module": "provenance",
            "label": "Source-search summary",
            "legacy_alias": True,
            "status": report.status.value,
            "result": report.status.value,
            "reasoning": search["reasoning"],
            "benchmark": None,
            "artifacts": [
                {
                    "kind": "web_appearance",
                    "label": "Source page",
                    "url": item.page_url,
                }
                for item in report.appearances
                if item.page_url and item.match_type is not MatchType.SIMILAR
            ],
            "limitations": report.limitations,
        })
    detail = _network_detail(case_id)
    network_checks = (
        build_network_checks(case_id, detail["payload"], detail["coverage"], case.modules["network"].model_dump(mode="json"), detail.get("tests"))
        if detail and "network" in case.modules
        else []
    )
    if detail and "network" in case.modules:
        # Keep the original aggregate ID available alongside the newer granular
        # network checks so existing clients can migrate without losing a result.
        network_result = case.modules["network"]
        coverage = detail["coverage"] or {}
        network_checks.append({
            "check_id": "network-trace",
            "module": "network",
            "label": "Public-post trace summary",
            "legacy_alias": True,
            "status": network_result.status.value,
            "result": network_result.status.value,
            "reasoning": "; ".join(network_result.evidence + network_result.limitations)
            or "No public-post trace details were recorded.",
            "benchmark": None,
            "artifacts": [
                {
                    "kind": "public_post",
                    "label": "Matching public post",
                    "url": item.get("permalink"),
                }
                for item in coverage.get("spread", [])
                if item.get("permalink")
            ],
            "limitations": network_result.limitations,
        })
    return build_explanation(case, media_detail.get("checks", []), provenance_checks, network_checks)


@app.post(HEATMAP_PATH, response_model=HeatmapResponse)
def media_heatmap(
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP. The file is deleted afterwards.")],
) -> HeatmapResponse:
    """Show where covering part of an image moved the model's score. Run only on request."""
    if not _heatmap_slot.acquire(blocking=False):
        raise HTTPException(status_code=429, detail={"code": "busy", "message": "A heatmap is already running. Try again shortly."})
    try:
        config = MediaConfig.from_env()
        with tempfile.NamedTemporaryFile(prefix="trustfeed-heatmap-", delete=False) as handle:
            path = Path(handle.name)
        try:
            with path.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
            # The same content and size checks as an upload, before anything is decoded.
            if inspect_input(path, config).media_type is not MediaType.IMAGE:
                raise MediaInputError("unsupported_type", "A heatmap can only be made for an image.")
            image, _, _ = read_image(path, config)
        except MediaInputError as error:
            status_code = MEDIA_REJECTION_STATUS.get(error.code, 422)
            raise HTTPException(status_code=status_code, detail={"code": error.code, "message": error.message}) from error
        finally:
            path.unlink(missing_ok=True)
        result = occlusion_heatmap(image, default_classifier(config), batch_size=config.batch_size)
        png = render_png(result) if result.changes else None
        return HeatmapResponse(
            status=result.status.value,
            label=result.label,
            grid_size=result.grid_size,
            base_score=result.base_score,
            max_change=result.max_change,
            notable=result.notable,
            reasoning=result.reasoning,
            limitations=result.limitations,
            png_base64=base64.b64encode(png).decode("ascii") if png else None,
        )
    finally:
        _heatmap_slot.release()


def _watch_refused(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@app.post("/api/monitors")
def create_monitor(request: MonitorStartRequest) -> dict[str, object]:
    """Register a watch. It sends nothing until it is polled, and nothing runs in the background."""
    if os.getenv("PROVENANCE_REPLAY_PATH"):
        raise _watch_refused(409, "replay_mode", "Replay mode stays offline, so monitoring is off.")
    watch_id = f"watch-{uuid4()}"
    try:
        return start_watch(
            watch_id,
            opted_in=request.opted_in,
            text=request.text,
            urls=tuple(str(url) for url in request.urls),
            hashtags=tuple(request.hashtags),
        )
    except WatchError as error:
        raise _watch_refused(422, "watch_refused", str(error)) from error


@app.get("/api/monitors")
def get_monitors() -> dict[str, list[str]]:
    return {"watches": list_watches()}


@app.post("/api/monitors/{watch_id}/poll")
def poll_monitor(watch_id: str) -> dict[str, Any]:
    """Poll once. Polls closer together than the limit are refused."""
    if watch_id not in list_watches():
        raise _watch_refused(404, "watch_not_found", "No such watch. It may have expired or been stopped.")
    try:
        return poll_watch(watch_id)
    except WatchError as error:
        raise _watch_refused(429, "polled_too_soon", str(error)) from error


@app.delete("/api/monitors/{watch_id}")
def delete_monitor(watch_id: str) -> dict[str, bool]:
    return {"stopped": stop_watch(watch_id)}


@app.get("/api/monitor/alerts", response_model=list[dict[str, Any]])
def get_monitor_alerts() -> list[dict[str, Any]]:
    demo_path = Path(__file__).resolve().parents[3] / "data" / "demo" / "network_demo.json"
    if not demo_path.is_file():
        return []
    try:
        data = json.loads(demo_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Failed to read network_demo.json for monitor alerts: %s", exc)
        return []

    posts = data.get("posts", [])
    campaigns: dict[str, dict[str, Any]] = {}
    for post in posts:
        key = post.get("media_hash") or post.get("url")
        if not key:
            continue
        key_str = str(key)
        if key_str not in campaigns:
            campaigns[key_str] = {
                "campaign_id": key_str,
                "platforms": set(),
                "total_posts": 0,
            }
        campaigns[key_str]["total_posts"] += 1
        platform = post.get("platform")
        if platform:
            campaigns[key_str]["platforms"].add(str(platform))

    alerts = []
    for camp in campaigns.values():
        total = camp["total_posts"]
        spread = sorted(camp["platforms"])
        if total >= 25 or len(spread) >= 3:
            risk = "critical"
        elif total >= 15:
            risk = "high"
        elif total >= 5:
            risk = "moderate"
        else:
            risk = "low"
        alerts.append({
            "campaign_id": camp["campaign_id"],
            "platform_spread": spread,
            "total_posts": total,
            "risk_level": risk,
        })
    alerts.sort(key=lambda x: x["total_posts"], reverse=True)
    return alerts


@app.get("/api/network/{case_id}")
def get_network(case_id: str) -> dict[str, list[dict[str, object]]]:
    detail = _network_detail(case_id)
    if detail is not None:
        return detail["payload"]
    _find_case(case_id)
    return {"nodes": [], "edges": [], "timeline": []}


@app.get("/api/network/{case_id}/tests")
def get_tests(case_id: str) -> dict[str, object] | None:
    """Say whether the pattern is more than chance. Null means no trace ran for this case."""
    detail = _network_detail(case_id)
    if detail is None:
        _find_case(case_id)
        return None
    return detail.get("tests")


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
    return fusion_action_packet(case, request.audience)
