"""Recorded results for the demo. Reading them never touches the network."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from backend.provenance.models import ProvenanceReport, Status

DEMO_CASE_ID = "demo-001"
DEFAULT_REPLAY_PATH = Path(__file__).resolve().parents[2] / "data" / "demo" / "provenance_demo.json"


def _load(path: Path) -> dict:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def _unavailable(reason: str, sha256: str | None = None) -> ProvenanceReport:
    return ProvenanceReport(status=Status.UNAVAILABLE, replay=True, media_sha256=sha256, limitations=[reason])


def replay_report(path: Path, sha256: str) -> ProvenanceReport:
    """Return the recorded search for this exact file. Other files get no result."""
    entry = _load(path).get("recorded", {}).get(sha256)
    if not isinstance(entry, dict):
        return _unavailable("Replay mode has no recorded search for this image, so no search was run.", sha256)
    try:
        report = ProvenanceReport.model_validate(entry["report"])
    except (KeyError, ValidationError):
        return _unavailable("The recorded search for this image could not be read.", sha256)
    return report.model_copy(update={"replay": True})


def get_demo_provenance(case_id: str, path: Path = DEFAULT_REPLAY_PATH) -> ProvenanceReport | None:
    """Return the synthetic report for the demo case, or None for any other case."""
    entry = _load(path).get("cases", {}).get(case_id)
    if not isinstance(entry, dict):
        return None
    report = ProvenanceReport.model_validate(entry)
    return report.model_copy(update={"replay": True, "synthetic": True, "case_id": case_id})


def record_report(path: Path, report: ProvenanceReport, *, licence: str, attribution: str) -> None:
    """Add a real search to the replay file, with the image's licence. Keys are never in reports."""
    if report.status is not Status.COMPLETE or report.searched_at is None or not report.media_sha256:
        raise ValueError("Only a completed live web search can be recorded.")
    document = _load(path)
    document.setdefault("recorded", {})[report.media_sha256] = {
        "licence": licence,
        "attribution": attribution,
        "report": report.model_dump(mode="json"),
    }
    Path(path).write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
