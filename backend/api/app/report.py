"""Build an investigation report from what a case's checks really found, and export it as PDF.

Nothing is inferred here. A part that didn't run says so, and the earliest appearance found is
never called the source. The PDF writer uses the standard library, so export can't fail on a
missing package. Its built-in fonts cover Western characters only, so others become "?".
"""

from __future__ import annotations

from textwrap import wrap
from typing import Any

from backend.api.app.explanation import build_countermeasures
from backend.api.app.models import AnalysisResponse, ModuleStatus, RiskLevel

_NOT_RUN = "not_checked"
_FOUND = "signs_found"
_NONE = "none_found"
_MAX_ITEMS = 25


def _section(status: str, items: list[str], note: str) -> dict[str, Any]:
    return {"status": status, "items": items[:_MAX_ITEMS], "note": note}


def _manipulated_media(case: AnalysisResponse) -> dict[str, Any]:
    media = case.modules.get("media")
    note = "A detector score is a signal for review, not proof. A quiet detector doesn't show media is authentic."
    if media is None or media.status is not ModuleStatus.COMPLETE:
        return _section(_NOT_RUN, [], media.limitations[0] if media and media.limitations else "No media was checked.")
    component = next((item for item in (case.unified_risk.components if case.unified_risk else []) if item.name == "media"), None)
    if component is not None and component.counted:
        return _section(_FOUND, media.evidence, note)
    return _section(_NONE, [], note)


def _misleading_context(case: AnalysisResponse, provenance: dict[str, Any] | None) -> dict[str, Any]:
    items = [item.explanation for item in case.cross_modal.conflicts] if case.cross_modal else []
    if case.claim_analysis:
        items += [item.explanation for item in case.claim_analysis.inconsistencies if item.severity == "note"]
    if provenance and provenance.get("earliest_found"):
        items.append("The image appeared earlier elsewhere. Compare that date with the date this post claims.")
    note = "A difference is a reason to look closer. It doesn't show that anyone meant to mislead."
    compared = bool(case.cross_modal and case.cross_modal.status is ModuleStatus.COMPLETE) or bool(provenance) or bool(case.claim_analysis)
    return _section(_FOUND if items else _NONE if compared else _NOT_RUN, items, note)


def _false_claims(case: AnalysisResponse) -> dict[str, Any]:
    items = [f"Contradicted by sources: {record.text}" for record in case.claims if record.verdict and record.verdict.value == "contradicted"]
    if case.claim_analysis:
        items += [item.explanation for item in case.claim_analysis.inconsistencies if item.severity == "conflict"]
    verified = bool(case.claim_analysis and case.claim_analysis.verification.status is ModuleStatus.COMPLETE)
    note = "Sources compared by model are signals, not proof. Finding nothing doesn't make a claim false or true."
    if items:
        return _section(_FOUND, items, note)
    return _section(_NONE if verified else _NOT_RUN, [], note if verified else "Claims were not compared with outside sources.")


def _scams(case: AnalysisResponse) -> dict[str, Any]:
    items = [f"{item.why} Found: {item.quote!r}" for item in case.scam_analysis.signs] if case.scam_analysis else []
    items += [item.why for item in case.link_analysis.signs] if case.link_analysis else []
    checked = case.scam_analysis is not None or case.link_analysis is not None
    return _section(_FOUND if items else _NONE if checked else _NOT_RUN, items, "A warning sign is a reason to look closer, not proof of a scam.")


def _submitted(case: AnalysisResponse) -> list[str]:
    lines = []
    if case.claims:
        lines.append(f"Text, split into {len(case.claims)} statement(s).")
    if case.link_analysis:
        lines.append(f"A link on {case.link_analysis.requested_host}.")
    media = case.modules.get("media")
    if media and media.status is not ModuleStatus.NOT_APPLICABLE:
        lines.append("An image or video.")
    return lines or ["No content was submitted. This is a demonstration case."]


def _sources(case: AnalysisResponse, provenance: dict[str, Any] | None, network: dict[str, Any] | None) -> list[dict[str, Any]]:
    consulted: list[dict[str, Any]] = []
    if case.claim_analysis:
        consulted += [
            {"name": item.name, "kind": "claim search", "status": item.status.value, "detail": item.reason or f"{item.result_count} result(s)"}
            for item in case.claim_analysis.verification.providers
        ]
    for item in (provenance or {}).get("providers", []):
        consulted.append({"name": item["name"], "kind": "source search", "status": item["status"], "detail": item.get("limitation") or f"{item.get('result_count', 0)} result(s)"})
    for item in ((network or {}).get("coverage") or {}).get("platforms", []):
        consulted.append({"name": item.get("label", "platform"), "kind": "public posts", "status": item.get("status", "unknown"), "detail": item.get("reason") or ""})
    if case.link_analysis:
        link = case.link_analysis
        consulted.append({"name": "The link itself", "kind": "link check", "status": link.page.status.value, "detail": link.page.reason or "Page read."})
        consulted.append({"name": link.domain.source or "rdap.org", "kind": "domain registry", "status": link.domain.status.value, "detail": link.domain.reason or f"Registered {link.domain.registered_on}."})
        consulted.append({"name": "Threat lists", "kind": "reputation", "status": link.threat_lists.status.value, "detail": link.threat_lists.reason or ""})
    return consulted


def _evidence(case: AnalysisResponse) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    supporting, contradicting = [], []
    for record in case.claims:
        for source in record.sources:
            entry = {"claim": record.text, "title": source.title, "url": source.url, "domain": source.domain, "date": source.date, "why": source.explanation}
            if source.stance == "supports":
                supporting.append(entry)
            elif source.stance == "contradicts":
                contradicting.append(entry)
    return supporting[:_MAX_ITEMS], contradicting[:_MAX_ITEMS]


def _appearances(provenance: dict[str, Any] | None) -> dict[str, Any]:
    if not provenance:
        return {"status": _NOT_RUN, "earliest_found": None, "appearances": [], "note": "No source search ran."}
    earliest = provenance.get("earliest_found")
    return {
        "status": provenance.get("status"),
        "earliest_found": {"observed_at": earliest["observed_at"], "caveat": earliest["caveat"]} if earliest else None,
        "appearances": [
            {"domain": item.get("domain"), "url": item.get("page_url"), "match": item.get("match_type"), "observed_at": item.get("observed_at")}
            for item in provenance.get("appearances", [])[:_MAX_ITEMS]
        ],
        "note": "The earliest appearance found is not necessarily the original source.",
    }


def _spread(case: AnalysisResponse, network: dict[str, Any] | None) -> dict[str, Any]:
    if not network:
        module = case.modules.get("network")
        return {"status": _NOT_RUN, "note": module.limitations[0] if module and module.limitations else "No public-post trace ran."}
    payload = network.get("payload") or {}
    tests = network.get("tests") or {}
    nodes = payload.get("nodes", [])
    return {
        "status": "complete",
        "synthetic": any(node.get("synthetic") for node in nodes),
        "accounts": len(nodes),
        "accounts_in_flagged_groups": sum(1 for node in nodes if node.get("in_flagged_cluster")),
        "null_test": (tests.get("null_test") or {}).get("reason"),
        "bursts": len((tests.get("bursts") or {}).get("bursts", [])),
        "note": "This describes how content spread. It doesn't show that accounts are coordinating, or that content is false.",
    }


def build_report(case: AnalysisResponse, provenance: dict[str, Any] | None, network: dict[str, Any] | None) -> dict[str, Any]:
    supporting, contradicting = _evidence(case)
    unified = case.unified_risk
    uncertain = list(case.uncertainties)
    uncertain += [f"{item.label}: {item.note}" for item in (unified.components if unified else []) if item.note and item.status is ModuleStatus.UNAVAILABLE]
    actions = list(dict.fromkeys([*case.recommended_actions, *build_countermeasures(case)]))
    return {
        "investigation_id": case.case_id,
        "created_at": case.created_at.isoformat(),
        "replay_label": case.replay_label,
        "submitted": _submitted(case),
        "detected": {
            "level": case.overall_risk.value,
            "summary": case.summary,
            "score": unified.score if unified else None,
            "trust_score": unified.trust_score if unified else None,
            "components": [item.model_dump(mode="json") for item in unified.components] if unified else [],
        },
        "findings": {
            "manipulated_media": _manipulated_media(case),
            "misleading_context": _misleading_context(case, provenance),
            "false_claims": _false_claims(case),
            "scams": _scams(case),
        },
        "sources_consulted": _sources(case, provenance, network),
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "earlier_appearances": _appearances(provenance),
        "spread": _spread(case, network),
        "uncertain": list(dict.fromkeys(uncertain)),
        "recommended_actions": actions,
        "notice": "A triage signal for human review, not a factual verdict.",
    }


_FINDING_TITLES = {
    "manipulated_media": "Manipulated media",
    "misleading_context": "Misleading context",
    "false_claims": "False claims",
    "scams": "Scams",
}
_STATUS_WORDS = {_FOUND: "signs found", _NONE: "none found (this doesn't show it's safe)", _NOT_RUN: "not checked"}


def _report_lines(report: dict[str, Any]) -> list[tuple[str, str]]:
    """Flatten the report into (style, text) lines, with style "h1", "h2" or "p"."""
    lines: list[tuple[str, str]] = [("h1", "TrustFeed investigation report"), ("p", report["notice"])]
    if report["replay_label"]:
        lines.append(("p", f"REPLAY: {report['replay_label']}"))

    def section(title: str, items: list[str]) -> None:
        lines.append(("h2", title))
        lines.extend(("p", item) for item in (items or ["Nothing to report."]))

    detected = report["detected"]
    trust = detected["trust_score"]
    section("Investigation", [f"ID: {report['investigation_id']}", f"Created: {report['created_at']}"])
    section("What was submitted", report["submitted"])
    section(
        "What was detected",
        [
            f"Level: {detected['level']}",
            detected["summary"],
            f"Trust score: {trust if trust is not None else 'none, as nothing measured reached a result'}",
            *[
                f"{item['label']}: {'scored' if item['counted'] else 'not scored'}"
                + (f", {item['score']:.2f}" if item["score"] is not None else "")
                for item in detected["components"]
                if item["status"] != "not_applicable" or item["counted"]
            ],
        ],
    )
    for key, title in _FINDING_TITLES.items():
        finding = report["findings"][key]
        section(f"{title}: {_STATUS_WORDS[finding['status']]}", [*finding["items"], finding["note"]])
    section("Sources consulted", [f"{item['name']} ({item['kind']}): {item['status']}. {item['detail']}" for item in report["sources_consulted"]])
    for key, title in (("supporting_evidence", "Supporting evidence"), ("contradicting_evidence", "Contradicting evidence")):
        section(title, [f"{item['title']} ({item['domain']}), {item['date'] or 'no date'}: {item['why']}" for item in report[key]])
    earlier = report["earlier_appearances"]
    earliest = earlier["earliest_found"]
    section(
        "Earlier appearances",
        [
            *([f"Earliest found: {earliest['observed_at']}. {earliest['caveat']}"] if earliest else []),
            *[f"{item['domain'] or 'unknown'}, {item['match']}, {item['observed_at'] or 'no date'}" for item in earlier["appearances"]],
            earlier["note"],
        ],
    )
    spread = report["spread"]
    section(
        "Spread",
        (
            [
                *(["SYNTHETIC DEMO DATA, not real activity."] if spread.get("synthetic") else []),
                f"{spread['accounts']} accounts, {spread['accounts_in_flagged_groups']} in flagged groups, {spread['bursts']} burst(s).",
                *([spread["null_test"]] if spread.get("null_test") else []),
                spread["note"],
            ]
            if spread["status"] == "complete"
            else [f"Not checked. {spread['note']}"]
        ),
    )
    section("What remains uncertain", report["uncertain"])
    section("Recommended actions", report["recommended_actions"])
    return lines


_PAGE_WIDTH, _PAGE_HEIGHT, _MARGIN = 595, 842, 50
_STYLES = {"h1": ("F2", 18, 60, 26), "h2": ("F2", 12, 80, 20), "p": ("F1", 10, 95, 14)}


def _pdf_text(text: str) -> str:
    """Keep what the built-in font can show, and escape what PDF syntax treats as special."""
    plain = "".join(ch if ch.isprintable() else " " for ch in text)
    safe = plain.encode("cp1252", errors="replace").decode("cp1252")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_string(text: str) -> bytes:
    return _pdf_text(text).encode("cp1252")


def render_pdf(report: dict[str, Any]) -> bytes:
    pages: list[list[bytes]] = [[]]
    y = _PAGE_HEIGHT - _MARGIN
    for style, text in _report_lines(report):
        font, size, width, height = _STYLES[style]
        for line in wrap(text, width, break_long_words=True, replace_whitespace=True) or [""]:
            if y - height < _MARGIN:
                pages.append([])
                y = _PAGE_HEIGHT - _MARGIN
            y -= height
            pages[-1].append(b"BT /%s %d Tf %d %d Td (" % (font.encode(), size, _MARGIN, y) + _pdf_string(line) + b") Tj ET")

    objects: list[bytes] = []
    kids = " ".join(f"{5 + index * 2} 0 R" for index in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    for index, commands in enumerate(pages):
        stream = b"\n".join(commands)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_WIDTH} {_PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {6 + index * 2} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    table = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    output += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, table)
    return bytes(output)


# Dashboard overview


def case_kinds(case: AnalysisResponse) -> set[str]:
    """Which filters a case matches, from what its checks found."""
    kinds = set()
    media = case.modules.get("media")
    if media and media.status is not ModuleStatus.NOT_APPLICABLE:
        kinds.add("media")
    if case.link_analysis:
        kinds.add("link")
    if case.claims:
        kinds.add("text")
    if case.scam_analysis and case.scam_analysis.signs:
        kinds.add("scam")
    network = case.modules.get("network")
    if network and network.score is not None:
        kinds.add("campaign")
    return kinds


def build_overview(cases: list[AnalysisResponse], total: int) -> dict[str, Any]:
    """Counts across saved cases. Replays are counted apart, so demos can't look like real findings."""
    real = [case for case in cases if not case.is_replay]
    distribution = {level.value: 0 for level in RiskLevel}
    media_assessments = {"signals": 0, "no_strong_signal": 0, "unavailable": 0}
    urls, claims, campaigns, alerts = [], [], [], []
    for case in real:
        distribution[case.overall_risk.value] += 1
        media = case.modules.get("media")
        if media and media.status is not ModuleStatus.NOT_APPLICABLE:
            counted = any(item.name == "media" and item.counted for item in (case.unified_risk.components if case.unified_risk else []))
            key = "signals" if counted else "no_strong_signal" if media.status is ModuleStatus.COMPLETE else "unavailable"
            media_assessments[key] += 1
        link = case.link_analysis
        if link and link.signs:
            urls.append({"case_id": case.case_id, "host": link.requested_host, "assessment": link.assessment, "signs": len(link.signs)})
        claims += [
            {"case_id": case.case_id, "text": record.text[:200], "verdict": record.verdict.value if record.verdict else "unverified"}
            for record in case.claims
            if record.checkable and (not record.verdict or record.verdict.value != "supported")
        ]
        network = case.modules.get("network")
        if network and network.score is not None:
            campaigns.append({"case_id": case.case_id, "score": network.score})
        if case.overall_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            alerts.append({"case_id": case.case_id, "level": case.overall_risk.value, "created_at": case.created_at.isoformat(), "summary": case.summary})
    return {
        "investigations": len(real),
        "replays": len(cases) - len(real),
        "total_saved": total,
        "read_limit_reached": total > len(cases),
        "risk_distribution": distribution,
        "media_assessments": media_assessments,
        "suspicious_urls": urls[:20],
        "claims_to_verify": claims[:20],
        "flagged_campaigns": campaigns[:20],
        "recent_high_risk": alerts[:10],
    }
