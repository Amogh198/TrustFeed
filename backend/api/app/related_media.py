"""Join the spread histories of cases holding the same picture into one time-ordered list."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from backend.api.app.models import (
    RelatedMediaCase,
    RelatedMediaEvent,
    RelatedMediaResponse,
)
from backend.media.fingerprint import CaseFingerprint
from backend.media.related import MAX_LINKS_FROM_START, related_cases

MAX_EVENTS = 300
LIMITATIONS = [
    "A link means the pictures look alike. It doesn't show who made them, or that the people posting them are connected.",
    f"Cases can be joined through one other case, up to {MAX_LINKS_FROM_START} matches away, so two of them may look less alike than either does to the case between them. One wrong match can also join unrelated cases, so check each link.",
    "Only cases saved on this account are compared, and only what those cases found is listed. Cases saved while signed out are compared with each other, because they share one case list.",
    "Shares visible content can mean a heavy crop of one picture, but two different pictures sharing a logo, a screenshot frame or text can also match. Those matches link only to this case, never onward through another case.",
    "Earliest found means earliest among these results. It is not shown to be the source.",
]
NO_FINGERPRINTS = "This case has no saved picture fingerprints, so nothing could be compared."


def _public_posts(case_id: str, network: dict[str, Any] | None) -> Iterable[RelatedMediaEvent]:
    coverage = (network or {}).get("coverage") or {}
    synthetic = coverage.get("synthetic") is True
    for post in coverage.get("spread") or []:
        yield RelatedMediaEvent(
            at=post.get("posted_at"),
            kind="public_post",
            case_id=case_id,
            label=post.get("handle") or "Public post",
            platform=post.get("platform"),
            url=None if synthetic else post.get("permalink"),
            matched_on=post.get("matched_on"),
            synthetic=synthetic,
        )


def _web_pages(case_id: str, provenance: dict[str, Any] | None) -> Iterable[RelatedMediaEvent]:
    synthetic = (provenance or {}).get("synthetic") is True
    for item in (provenance or {}).get("appearances") or []:
        yield RelatedMediaEvent(
            at=item.get("observed_at"),
            kind="web_page",
            case_id=case_id,
            label=item.get("domain") or item.get("page_title") or "Web page",
            platform=item.get("platform"),
            url=None if synthetic else item.get("page_url"),
            matched_on=item.get("match_type"),
            date_source=item.get("date_source"),
            synthetic=synthetic,
        )


def _combined(events: Iterable[RelatedMediaEvent]) -> list[RelatedMediaEvent]:
    """Sort by date with undated items last, list each link once, and mark the earliest real item found."""
    seen: set[str] = set()
    unique = []
    for event in sorted(events, key=lambda item: (item.at is None, item.at or "")):
        if event.url:
            if event.url in seen:
                continue
            seen.add(event.url)
        unique.append(event)
    for event in unique:
        if event.at and event.kind != "submitted" and not event.synthetic:
            event.earliest_found = True
            break
    return unique[:MAX_EVENTS]


def build_related_media(
    case_id: str,
    records: list[CaseFingerprint],
    get_detail: Callable[[str, str], dict[str, Any] | None],
    get_network: Callable[[str], dict[str, Any] | None],
) -> RelatedMediaResponse:
    """Find a case's related cases among one owner's records and connect what each one found."""
    start = next((record for record in records if record.case_id == case_id), None)
    if start is None:
        return RelatedMediaResponse(case_id=case_id, status="not_applicable", reason=NO_FINGERPRINTS, limitations=LIMITATIONS)
    related = related_cases(start, records)
    events: list[RelatedMediaEvent] = []
    if related:
        for member, seen_at in [(case_id, start.seen_at), *((item.case_id, item.first_seen) for item in related)]:
            events.append(RelatedMediaEvent(at=seen_at, kind="submitted", case_id=member, label="Checked here"))
            events.extend(_public_posts(member, get_network(member)))
            events.extend(_web_pages(member, get_detail(member, "provenance")))
    return RelatedMediaResponse(
        case_id=case_id,
        status="complete",
        compared_cases=max(0, len(records) - 1),
        cases=[
            RelatedMediaCase(
                case_id=item.case_id,
                kind=item.kind,
                first_seen=item.first_seen,
                through_case_id=item.through_case_id,
                links_from_start=item.links_from_start,
                distances=item.distances,
                agreeing_features=item.agreeing_features,
            )
            for item in related
        ],
        history=_combined(events),
        limitations=LIMITATIONS,
    )
