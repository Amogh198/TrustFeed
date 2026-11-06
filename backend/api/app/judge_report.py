"""The investigation report, as sections both the dashboard and the PDF draw, so they can't disagree.

Everything here is read from what the checks stored. A value that wasn't recorded says so, and the
score arithmetic is recomputed from the stored components and compared with the stored result.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid5, NAMESPACE_URL

from backend.api.app import risk
from backend.api.app.models import AnalysisResponse, ModuleStatus
from backend.network.config import CoordinationConfig

BENCHMARK = Path(__file__).resolve().parents[3] / "data" / "eval" / "commons_licensed_2026-11-05.json"
NOT_RECORDED = "Not recorded"
_MAX_ROWS = 60
_SOURCES = {"nonescape/nonescape-mini-v0": "https://nonescape.sfo2.cdn.digitaloceanspaces.com/nonescape-mini-v0.safetensors"}
_NOT_RUN_WORDS = ("not requested", "not allowed", "no public-post trace", "not submitted", "stays offline", "no media was submitted", "no source search")


def _link(text: Any, url: str | None) -> dict[str, str] | str:
    value = str(text) if text not in (None, "") else NOT_RECORDED
    try:
        safe = bool(url) and urlsplit(url).scheme in {"http", "https"}
    except ValueError:
        safe = False
    return {"text": value, "url": url} if safe else value


def _value(value: Any) -> str:
    if value is None or value == "" or value == [] or value == {}:
        return NOT_RECORDED
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _stamp(value: Any) -> str:
    """Give the time in UTC and in this server's local zone, naming each."""
    if not value:
        return NOT_RECORDED
    try:
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if moment.tzinfo is None:
        return f"{moment.isoformat()} (time zone not recorded)"
    local = moment.astimezone()
    return f"{moment.astimezone(UTC).isoformat(timespec='seconds')} | {local.strftime('%d %b %Y, %H:%M:%S %Z')}"


def _kv(rows: list[tuple[str, Any]], copy: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "kv",
        "rows": [
            {"label": label, "value": value if isinstance(value, dict) else _value(value), "copy": label in copy}
            for label, value in rows
        ],
    }


def _table(columns: list[str], rows: list[list[Any]], empty: str) -> dict[str, Any]:
    if not rows:
        return {"type": "text", "text": empty}
    return {"type": "table", "columns": columns, "rows": [[c if isinstance(c, dict) else _value(c) for c in row] for row in rows[:_MAX_ROWS]], "omitted": max(0, len(rows) - _MAX_ROWS)}


def _text(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def _items(items: list[str], empty: str = "Nothing recorded.") -> dict[str, Any]:
    return {"type": "list", "items": items} if items else _text(empty)


def _section(number: int, title: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": f"s{number}", "title": f"{number}. {title}", "blocks": blocks}


class _Register:
    """Number each observation, so a claim can point at what supports it."""

    def __init__(self) -> None:
        self.rows: list[list[Any]] = []

    def add(self, module: str, observation: str, source: Any, when: Any, method: str, result: str, strength: Any = None, limits: str = "") -> str:
        evidence_id = f"E{len(self.rows) + 1}"
        self.rows.append([evidence_id, module, observation, source, _stamp(when) if when else "No time applies", method, result, strength if strength is not None else "Not measured", limits or "See section 11"])
        return evidence_id


def _status(name: str, module: Any, case: AnalysisResponse) -> tuple[str, str]:
    if module is None:
        return "Not run", "This case was saved before this check existed."
    reason = (module.limitations or [""])[0]
    if module.status is ModuleStatus.NOT_APPLICABLE:
        return "Not applicable", reason
    if module.status is ModuleStatus.UNAVAILABLE:
        return ("Not run" if any(word in reason.casefold() for word in _NOT_RUN_WORDS) else "Unavailable"), reason
    if name == "url" and case.link_analysis and case.link_analysis.live_failed:
        return "Partial", "Some live link checks could not finish."
    if name == "media" and case.overall_risk.value == "inconclusive":
        return "Inconclusive", "It ran, and gave no clear result."
    if name == "network" and any("Inconclusive" in line for line in module.limitations):
        return "Inconclusive", next(line for line in module.limitations if "Inconclusive" in line)
    return "Complete", "It ran."


def _benchmark() -> dict[str, dict[str, Any]]:
    try:
        models = json.loads(BENCHMARK.read_text(encoding="utf-8")).get("models", [])
    except (OSError, ValueError):
        return {}
    found = {}
    for model in models:
        bands = model.get("current_bands") or {}
        part = bands.get("test") or bands.get("all_images") or {}
        found[model.get("model_id")] = {"split": "test" if "test" in bands else "all images", "recall": part.get("recall"), "fpr": part.get("false_positive_rate"), "auc": part.get("auc")}
    return found


def _rate(item: Any) -> str:
    return f"{item['count']} of {item['total']}" if isinstance(item, dict) and "total" in item else NOT_RECORDED


def _score_blocks(case: AnalysisResponse) -> tuple[list[dict[str, Any]], list[str]]:
    unified = case.unified_risk
    missing: list[str] = []
    if unified is None:
        return [_text("This case has no component breakdown, as it was saved before unified scoring or is a demonstration case. Its level can't be reconstructed here.")], ["Component breakdown for this case"]
    counted = [item for item in unified.components if item.counted]
    remaining = 1.0
    rows = []
    for item in counted:
        contribution = item.weight * (item.score or 0.0)
        remaining *= 1 - contribution
        rows.append([item.label, f"{item.score:.4f}" if item.score is not None else "None", item.weight, f"{contribution:.4f}", f"{remaining:.4f}", _value(item.results_file)])
    recomputed = round(1 - remaining, 3)
    blocks: list[dict[str, Any]] = [
        _text("Formula: score = 1 - product of (1 - weight x component score), over the counted components. It's in backend/api/app/risk.py. Scores are uncalibrated triage signals, not probabilities."),
        _table(["Counted component", "Component score", "Weight", "Weight x score", "Remaining after this", "Results file"], rows, "No component was counted."),
    ]
    stored = unified.score
    if rows:
        arithmetic = f"Arithmetic: 1 - {remaining:.4f} = {recomputed:.3f}. Stored score: {stored if stored is not None else NOT_RECORDED}."
        calculation = unified.calculation or {}
        if (calculation.get("vote") or {}).get("web_decides"):
            arithmetic += " The stored score is 0 because web search decided this case and the detectors were ignored."
        elif stored is not None and abs(stored - recomputed) > 0.001:
            arithmetic += " These differ, and the difference is unexplained."
            missing.append("Reason the stored score differs from the formula")
        blocks.append(_text(arithmetic))
    levels = ", ".join(f"{level.value} from {floor}" for floor, level in risk._THRESHOLDS)
    blocks.append(_text(f"Level thresholds: {levels}, otherwise low. A low score reads inconclusive when an unscored check needs review or nothing measured reached a result."))
    blocks.append(_table(
        ["Not scored", "Status", "Why", "Evidence raised"],
        [[item.label, item.status.value, item.note or NOT_RECORDED, len(item.evidence)] for item in unified.components if not item.counted],
        "Every component was counted.",
    ))
    blocks.append(_kv([("Trust score", unified.trust_score), ("How it was worked out", unified.trust_note)]))
    return blocks, missing


def _vote_explanation(case: AnalysisResponse, media: dict[str, Any] | None) -> list[str]:
    """Say what each media number is, using this case's own values."""
    unified = case.unified_risk
    module = case.modules.get("media")
    vote = ((unified.calculation or {}).get("vote") or {}) if unified else {}
    if not unified or not module or module.score is None:
        return []
    component = next((item for item in unified.components if item.name == "media"), None)
    model = ((media or {}).get("checks", {}).get("classifier") or {}).get("model_id") or NOT_RECORDED
    lines = [f"Media module score {module.score}: the default detector alone ({model})."]
    if vote:
        lines.append(f"Average of the voting detectors {vote.get('raw_mean', 0):.4f}: the mean of the detectors in the table below. {vote.get('flagged')} of {vote.get('total')} reached the vote line of {risk.VOTE_LINE}.")
    if component and component.score is not None:
        lines.append(f"Unified media component {component.score}: what the scoring used. It follows from the average, capped at {risk._MEDIA_CAP} for a high result and at 0.59 for a moderate one.")
    if unified.score is not None:
        lines.append(f"Unified risk score {unified.score}: the formula above, rounded to 3 places.")
    return lines


def build_sections(
    case: AnalysisResponse,
    submission: dict[str, Any] | None,
    media: dict[str, Any] | None,
    provenance: dict[str, Any] | None,
    network: dict[str, Any] | None,
) -> dict[str, Any]:
    register = _Register()
    missing: list[str] = []
    checks = (media or {}).get("checks") or {}
    meta = checks.get("metadata") or {}
    fingerprint = checks.get("fingerprint") or {}
    phash = checks.get("phash") or {}
    panel = (checks.get("detector_panel") or {}).get("detectors") or []
    unified = case.unified_risk
    decision = unified.media_decision if unified else None
    synthetic = case.is_replay or case.case_id.startswith("demo-") or bool(((network or {}).get("coverage") or {}).get("synthetic"))
    mode = "Synthetic demonstration or offline replay, not live evidence" if synthetic else "Live analysis"
    generated = datetime.now(UTC)

    # Evidence first, so the summary can cite it.
    claims = []
    for item in case.scam_analysis.signs if case.scam_analysis else []:
        claims.append(register.add("Scam rules", item.why, "Fixed rule", case.created_at, "Phrase rule", f"{item.strength} sign, found: {item.quote}", limits="A sign isn't proof of a scam."))
    for item in case.link_analysis.signs if case.link_analysis else []:
        claims.append(register.add("Link", item.why, case.link_analysis.requested_host, case.created_at, "Link rules, feeds and live checks", f"{item.strength} sign", limits="A sign isn't proof."))
    if case.link_analysis and case.link_analysis.model_score is not None:
        claims.append(register.add("Link", "Link model scored the host name", "backend/text/link_model.npz", case.created_at, "Logistic regression on host text", f"{case.link_analysis.model_score:.3f}", limits="Reads the host name only."))
    for item in panel:
        if item.get("score") is not None and item.get("model_id") in risk.VOTING_DETECTORS:
            claims.append(register.add("Media", "Detector score", _link(item["model_id"], _SOURCES.get(item["model_id"], f"https://huggingface.co/{item['model_id']}")), case.created_at, "Image model", f"{item['score']:.4f}", limits="Uncalibrated. Not proof."))
    if not panel and case.modules.get("media") and case.modules["media"].score is not None:
        claims.append(register.add("Media", "Detector score", _value((checks.get("classifier") or {}).get("model_id")), case.created_at, "Image model", str(case.modules["media"].score), limits="Uncalibrated. Not proof."))
    appearance_rows = []
    for item in (provenance or {}).get("appearances", []):
        verified = f"Compared, pHash distance {item['phash_distance']}" if item.get("phash_distance") is not None else "Not compared directly: uses the provider's label"
        evidence = register.add("Source search", f"Image found on {item.get('domain') or 'a page'} ({item.get('match_type')})", _link(item.get("domain"), item.get("page_url")), item.get("observed_at"), f"{item.get('provider')}", str(item.get("match_type")), item.get("phash_distance"), "A match doesn't show who made it first.")
        claims.append(evidence)
        appearance_rows.append([evidence, _value(item.get("page_title")), _link(item.get("page_url"), item.get("page_url")), item.get("domain"), item.get("match_type"), item.get("provider"), _stamp(item.get("observed_at")), item.get("date_source"), item.get("date_evidence"), verified])
    if appearance_rows and not any(row[6] != NOT_RECORDED for row in appearance_rows):
        missing.append("Dates for the source search results")
    spread = ((network or {}).get("coverage") or {}).get("spread") or []
    post_rows = []
    for post in spread:
        evidence = register.add("Network", f"Post on {post.get('platform')}", _link(post.get("permalink") or post.get("account_id"), post.get("permalink")), post.get("posted_at"), "Public search", f"matched on {post.get('matched_on')}", limits="Posting isn't proof of coordination.")
        post_rows.append([evidence, post.get("platform"), _link(post.get("permalink") or "Synthetic post, no page", post.get("permalink")), post.get("handle") or post.get("account_id"), _stamp(post.get("posted_at")), post.get("matched_on"), "Carries the searched link, text or tag. Whether it holds the media itself isn't recorded."])
    for claim in case.claims:
        if claim.verdict and claim.verdict.value != "unverified":
            claims.append(register.add("Claims", claim.text[:160], "Public sources compared by model", case.created_at, "Source search and comparison model", claim.verdict.value, limits="A signal, not proof."))
    for item in case.cross_modal.conflicts if case.cross_modal else []:
        claims.append(register.add("Cross-modal", item.explanation, ", ".join(item.channels), case.created_at, "Date, place, figure and negation compare", item.severity, limits="OCR and speech contain errors."))

    # 1 and 2
    report_id = str(uuid5(NAMESPACE_URL, f"trustfeed-report:{case.case_id}"))
    overview = _section(1, "Case overview", [_kv([
        ("Case ID", case.case_id), ("Report ID", report_id), ("Risk level", case.overall_risk.value), ("Trust score", unified.trust_score if unified else None),
        ("Mode", mode), ("Report generated", _stamp(generated)),
    ], copy=("Case ID", "Report ID"))] + ([_text(f"SYNTHETIC OR REPLAY DATA: {case.replay_label or 'This case is a demonstration.'}")] if synthetic else []))
    cited = ", ".join(claims[:8]) or "no evidence item"
    summary_blocks: list[dict[str, Any]] = [_text(case.summary), _text(f"Supporting evidence: {cited}. See section 10.")]
    if decision:
        summary_blocks.append(_kv([("AI detectors say", f"{decision.detector_verdict}. {decision.detector_detail}"), ("Web search says", f"{decision.web_verdict}. {decision.web_detail}"), ("Combined", decision.combined)]))
    summary = _section(2, "Executive summary", summary_blocks)

    # 3
    if submission is None:
        missing.append("Submission details, as this case was saved before they were recorded")
    sub = submission or {}
    frames = (checks.get("keyframes") or {}).get("frames") or []
    hash_rows = [(f"{name} (perceptual)", value) for name, value in (fingerprint.get("hashes") or {}).items()]
    submission_section = _section(3, "Submission details and fingerprints", [
        _kv([
            ("Submitted at", _stamp(sub.get("submitted_at"))), ("Analysis started", _stamp(sub.get("started_at"))), ("Analysis completed", _stamp(sub.get("completed_at"))),
            ("Original file name", sub.get("file_name")), ("MIME type, as sent by the browser", sub.get("content_type")), ("File size in bytes", (media or {}).get("size_bytes")),
            ("Format", meta.get("format")), ("Width and height", f"{meta.get('width')} x {meta.get('height')}" if meta.get("width") else None),
            ("Video duration in seconds", meta.get("duration_s")), ("Frame count", meta.get("frame_count")), ("Frames per second", meta.get("fps")),
            ("Frames sampled", len(frames) if frames else None), ("Frame sampling", (checks.get("keyframes") or {}).get("strategy")),
            ("Input types", ", ".join(sub.get("inputs") or [])), ("Outside search allowed", sub.get("search_web")),
        ]),
        _text("These times are when this system received and analyzed the content. They aren't when the media was created."),
        _kv([("SHA-256 of the submitted file", fingerprint.get("sha256")), ("pHash", phash.get("phash")), *hash_rows], copy=("SHA-256 of the submitted file", "pHash", *[row[0] for row in hash_rows])),
        _text(
            f"Comparison: {fingerprint.get('references_checked', 0)} reference images and {fingerprint.get('earlier_cases_checked', 0)} earlier cases were checked."
            if fingerprint.get("compared")
            else "No fingerprint comparison was performed, as no reference index was available. SHA-256 only matches the exact same file. Perceptual hashes can match changed copies, and a match isn't proof of identical content."
        ),
        _table(["Kind", "Found in", "Label or case", "First seen", "Source", "Distances"], [[m.get("kind"), m.get("found_in"), m.get("label") or m.get("case_id"), m.get("first_seen"), m.get("source"), json.dumps(m.get("distances") or {})] for m in fingerprint.get("matches", [])], "No fingerprint match was recorded."),
    ])

    # 4
    score_blocks, score_missing = _score_blocks(case)
    missing += score_missing
    explanation = _vote_explanation(case, media)
    if explanation:
        score_blocks.append(_items(explanation))
    score_section = _section(4, "Score calculation and component breakdown", score_blocks)

    # 5
    bench = _benchmark()
    detector_rows = []
    for item in panel:
        model_id = item.get("model_id")
        score = item.get("score")
        data = bench.get(model_id) or {}
        votes = model_id in risk.VOTING_DETECTORS
        detector_rows.append([
            _link(model_id, _SOURCES.get(model_id, f"https://huggingface.co/{model_id}")), item.get("model_revision"), item.get("status"), f"{score:.4f}" if score is not None else None,
            risk.VOTE_LINE if votes else "Not used", ("Flagged" if score >= risk.VOTE_LINE else "Not flagged") if votes and score is not None else "No vote", votes,
            f"Fakes flagged {_rate(data.get('recall'))}, real flagged {_rate(data.get('fpr'))} ({data.get('split')})" if data else NOT_RECORDED, "No",
        ])
    missing.append("Each detector's input preprocessing, class labels and scores for classes other than 'AI or fake', as the media check stores one score per detector")
    forensics = checks.get("forensics") or {}
    credentials = checks.get("content_credentials") or {}
    media_section = _section(5, "Media detection and forensics", [
        _table(["Detector", "Commit", "Status", "Score for 'AI or fake'", "Vote line", "Decision", "In the vote", "Benchmark", "Validated for this deployment"], detector_rows, "No detector panel ran for this case."),
        _text("The vote: a majority of the 3 voting detectors reads high. Detector agreement is shown by the Decision column. Model scores are not proof of authenticity or manipulation."),
        _kv([("EXIF present", meta.get("exif_present")), ("GPS present (coordinates never copied)", meta.get("has_gps")), ("Metadata names an AI generator", meta.get("generator_hint")), ("Metadata fields", ", ".join(f"{k}: {v}" for k, v in (meta.get("fields") or {}).items())), ("Indicators", ", ".join(meta.get("indicators") or []))]),
        _kv([("C2PA state", credentials.get("state")), ("Signer trust", credentials.get("signer_trust")), ("Signer", credentials.get("signer_organisation")), ("Why invalid", credentials.get("invalid_reason")), ("Claim generator", credentials.get("claim_generator")), ("C2PA check status", credentials.get("status"))]),
        _text("Missing EXIF or C2PA is common after re-saving or sharing, and isn't proof of manipulation."),
        _table(["Forensic test", "Status", "Score", "Limit", "Flagged", "Regions"], [[t.get("name"), t.get("status"), t.get("score"), t.get("limit"), t.get("flagged"), len(t.get("regions") or [])] for t in forensics.get("tests", [])], "No forensic test ran for this case."),
        _text("Forensic tests never change the score. Heatmaps are made on request from the Media tab, as the file isn't kept."),
        _table(["Face region", "Time (s)", "Detector scores"], [[f"{f.get('width')}x{f.get('height')} at {f.get('x')},{f.get('y')}", f.get("timestamp_s"), "; ".join(f"{s['model_id']}: {s['score']:.3f}" for s in f.get("scores", []))] for f in (checks.get("faces") or {}).get("faces", [])], "No face region was recorded. Faces are never identified."),
    ])

    # 6
    earliest = (provenance or {}).get("earliest_found")
    provider_rows = [[p.get("name"), p.get("status"), p.get("result_count"), p.get("limitation")] for p in (provenance or {}).get("providers", [])]
    source_section = _section(6, "Provenance and source timeline", [
        _table(["Search service", "Status", "Results", "Note"], provider_rows, "No source search ran for this case."),
        _kv([("Earliest indexed appearance", _stamp((earliest or {}).get("observed_at"))), ("Date source", (earliest or {}).get("date_source"))]),
        _text("The earliest appearance found isn't necessarily the original source or creation date."),
        _table(["Evidence", "Page title", "URL", "Domain", "Match", "Found by", "Date", "Date source", "How dated", "Verification"], appearance_rows, "No appearance was recorded. Finding nothing doesn't show the image isn't online."),
    ])

    # 7
    link = case.link_analysis
    link_rows = []
    if link:
        for label, part in (("Lookalike", link.lookalike), ("Redirects", link.redirects), ("Domain age", link.domain), ("Page", link.page), ("Official site", link.official), ("Threat feeds", link.threat_lists)):
            link_rows.append([label, part.status.value, getattr(part, "reason", None) or "Ran"])
    text_section = _section(7, "Text and URL checks", [
        _table(["Statement", "Kind", "Verdict", "Why", "Sources"], [[c.text, c.kind, c.verdict.value if c.verdict else "unverified", c.rationale, len(c.sources)] for c in case.claims], "No text was submitted."),
        _table(["Source", "Claim", "Stance", "Date", "Why"], [[_link(s.title, s.url), c.text[:80], s.stance, f"{s.date} ({s.date_kind})" if s.date else None, s.explanation] for c in case.claims for s in c.sources], "No source was compared with a claim."),
        _text(f"Scam assessment: {case.scam_analysis.assessment}." if case.scam_analysis else "Scam rules didn't run, as no text was submitted."),
        _table(["Link check", "Status", "Note"], link_rows, "No link was submitted."),
        _kv([("Requested host", link.requested_host), ("Final host", link.redirects.final_host), ("Domain registered", link.domain.registered_on), ("Domain age in days", link.domain.age_days), ("Page title", link.page.title), ("Link model score", link.model_score), ("Threat feeds read", ", ".join(link.threat_lists.sources)), ("Hosts in feeds", link.threat_lists.entries), ("On a feed", link.threat_lists.listed)]) if link else _text("No link details."),
    ])

    # 8
    tests = (network or {}).get("tests") or {}
    null_test = tests.get("null_test") or {}
    payload = (network or {}).get("payload") or {}
    clusters = (network or {}).get("clusters") or []
    config = CoordinationConfig()
    network_blocks: list[dict[str, Any]] = []
    if synthetic and network:
        network_blocks.append(_text("SYNTHETIC DATA: invented accounts and posts, not real activity."))
    network_blocks += [
        _table(["Evidence", "Platform", "Post", "Account", "Posted", "Matched on", "Contains the content?"], post_rows, "No matching post was recorded. No trace ran, or none was found."),
        _kv([
            ("Accounts", len(payload.get("nodes", [])) or None), ("Co-share links", sum(1 for e in payload.get("edges", []) if "co_share" in str(e.get("type"))) or None),
            ("Time window in seconds", config.window_seconds), ("Items a pair must repeat", config.min_shared_items), ("Smallest flagged cluster", config.min_cluster_size), ("Flagging score", config.flag_score_threshold),
            ("Shuffled timing result", null_test.get("verdict")), ("Observed repeating pairs", null_test.get("observed")), ("Average with shuffled timing", null_test.get("chance_mean")), ("p-value", null_test.get("p_value")), ("Shuffles", null_test.get("permutations")), ("Bursts", len((tests.get("bursts") or {}).get("bursts", [])) if tests else None),
        ]),
        _text(null_test.get("reason") or "No coordination test ran for this case."),
        _table(["Cluster", "Accounts", "Flagged", "Score", "Components and weights", "Distinct items", "Median delay (s)"], [[c.get("id"), c.get("size"), c.get("flagged"), c.get("coordination_risk_score"), json.dumps(c.get("score_components")), c.get("distinct_items"), c.get("median_delay_seconds")] for c in clusters], "No cluster was recorded."),
        _text("Cluster score: sum of weight x component, with weights in backend/network/clusters.py. Co-sharing doesn't show coordination, common ownership, automation or intent."),
    ]
    network_section = _section(8, "Network and coordination analysis", network_blocks)

    # 9
    cross = case.cross_modal
    cross_section = _section(9, "Cross-modal analysis", [
        _text((cross.reason or f"Compared {', '.join(cross.channels)}. Assessment: {cross.assessment}.") if cross else "No media was submitted, so nothing was compared."),
        _table(["Between", "Kind", "Severity", "Explanation"], [[", ".join(i.channels), i.kind, i.severity, i.explanation] for i in (cross.conflicts if cross else [])], "No difference was recorded."),
        _text(f"Image and caption match: {cross.image_caption.reason}") if cross else _text("Image and caption match: not run."),
    ])

    # 10
    register_section = _section(10, "Evidence register", [_table(["ID", "Module", "Observation", "Source", "Time", "Method", "Result", "Strength", "Limits"], register.rows, "No evidence item was recorded.")])

    # 11
    status_rows = []
    for name in ("text", "url", "media", "provenance", "network"):
        state, why = _status(name, case.modules.get(name), case)
        component_names = {"text": "scam", "url": "link", "media": "media"}
        component = next((c for c in (unified.components if unified else []) if c.name == component_names.get(name)), None)
        status_rows.append([name, state, why, "Scored" if component and component.counted else "Not scored"])
    for name, value, reason in (("claims", case.claim_analysis, "No text was submitted."), ("scam", case.scam_analysis, "No text was submitted."), ("cross-modal", cross, "No media was submitted.")):
        status_rows.append([name, "Complete" if value else "Not applicable", "It ran." if value else reason, "Scored" if name == "scam" and value else "Not scored"])
    limits_section = _section(11, "Limitations and uncertainty", [
        _table(["Module", "Status", "Why", "Effect on the score"], status_rows, ""),
        _items(list(dict.fromkeys([*case.uncertainties, *(line for m in case.modules.values() for line in m.limitations)]))[:30]),
    ])

    # 12
    observed = [case.summary]
    suggests = [decision.combined] if decision else [f"This content reads {case.overall_risk.value} as a triage signal."]
    conclusion = _section(12, "Conclusion and recommended actions", [
        _kv([("What was observed", f"{len(register.rows)} evidence items, listed in section 10."), ("What this suggests", " ".join(suggests))]),
        _text("What can't be concluded: this doesn't show the content is true, false, authentic or fake, who made it, or anyone's intent. A high level isn't proof. A low level isn't proof of safety."),
        _text("Needs a person: the source of the media, the context of any claim, and any decision to act on this."),
        _items(case.recommended_actions, "No action was recorded."),
    ])
    del observed

    # 13
    missing_list = list(dict.fromkeys(missing))
    audit = _section(13, "Technical audit information", [
        _kv([("Report ID", report_id), ("Case saved", _stamp(case.created_at)), ("Report generated", _stamp(generated)), ("Media result schema", (media or {}).get("schema_version")), ("Default detector", (checks.get("classifier") or {}).get("model_id")), ("Default detector commit", (checks.get("classifier") or {}).get("model_revision")), ("Benchmark file", BENCHMARK.name), ("Evidence items", len(register.rows))]),
        _text("Missing from the backend, so not shown in this report:"),
        _items(missing_list, "Nothing is known to be missing."),
    ])
    return {
        "report_id": report_id,
        "generated_at": generated.isoformat(timespec="seconds"),
        "synthetic": synthetic,
        "missing_data": missing_list,
        "sections": [overview, summary, submission_section, score_section, media_section, source_section, text_section, network_section, cross_section, register_section, limits_section, conclusion, audit],
    }


def _cell(cell: Any, styles: Any, style: str = "BodyText") -> Any:
    from xml.sax.saxutils import escape

    from reportlab.platypus import Paragraph

    if isinstance(cell, dict):
        return Paragraph(f'<a href="{escape(cell["url"], {chr(34): "&quot;"})}" color="#1a56b0">{escape(cell["text"])}</a>', styles[style])
    return Paragraph(escape(str(cell)), styles[style])


def render_report_pdf(report: dict[str, Any]) -> bytes:
    """Draw the same sections as the dashboard, with page numbers and clickable links."""
    from io import BytesIO
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("Cell", parent=styles["BodyText"], fontSize=7.5, leading=9.5, wordWrap="CJK"))
    styles.add(ParagraphStyle("HeadCell", parent=styles["Cell"], fontName="Helvetica-Bold", textColor=colors.white))
    page = landscape(A4)
    width = page[0] - 30 * mm
    story: list[Any] = [Paragraph("TrustFeed investigation report", styles["Title"]), Paragraph("A triage signal for human review, not a factual verdict.", styles["BodyText"]), Spacer(1, 6)]
    for section in report["sections"]:
        story.append(Paragraph(escape(section["title"]), styles["Heading2"]))
        for block in section["blocks"]:
            if block["type"] == "text":
                story.append(Paragraph(escape(block["text"]), styles["BodyText"]))
            elif block["type"] == "list":
                story += [Paragraph("- " + escape(item), styles["BodyText"]) for item in block["items"]]
            elif block["type"] == "kv":
                rows = [[_cell(row["label"], styles, "Cell"), _cell(row["value"], styles, "Cell")] for row in block["rows"]]
                table = Table(rows, colWidths=[width * 0.27, width * 0.73])
                table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke)]))
                story.append(table)
            elif block["type"] == "table":
                columns = len(block["columns"])
                rows = [[_cell(c, styles, "HeadCell") for c in block["columns"]]] + [[_cell(c, styles, "Cell") for c in row] for row in block["rows"]]
                table = Table(rows, colWidths=[width / columns] * columns, repeatRows=1)
                table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#27306b")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                story.append(table)
                if block.get("omitted"):
                    story.append(Paragraph(f"{block['omitted']} more rows are left out here.", styles["BodyText"]))
            story.append(Spacer(1, 5))

    def footer(canvas: Any, document: Any) -> None:
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(15 * mm, 8 * mm, f"Report {report['report_id']} | Generated {report['generated_at']}" + (" | SYNTHETIC OR REPLAY DATA" if report["synthetic"] else ""))
        canvas.drawRightString(page[0] - 15 * mm, 8 * mm, f"Page {document.page}")

    buffer = BytesIO()
    SimpleDocTemplate(buffer, pagesize=page, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=14 * mm, title="TrustFeed investigation report").build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
