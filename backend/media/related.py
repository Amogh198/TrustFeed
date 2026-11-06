"""Link a case to earlier cases holding the same picture, even when the files differ.

A link means the pictures look alike. It doesn't show who made either one, which came first in the world, or that
the accounts posting them are connected. Only hashes are compared, never the media itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from backend.media.fingerprint import (
    EXACT_COPY,
    CaseFingerprint,
    QueryFrame,
    find_matches,
    fingerprint_record,
)
from backend.media.local_features import MATCH_LIMIT, best_agreement
from backend.media.models import MediaAnalysisResult

NOT_CONFIGURED_PREFIX = "No earlier-case fingerprints are configured"
# Local features agree between these pictures, which can be a heavy crop of one picture or shared content like a logo.
SHARES_CONTENT = "shares_visible_content"
# One wrong match can join two unrelated groups, so a chain stops here. Reposts often resemble one original more
# than one another, so one step through another case is still useful.
MAX_LINKS_FROM_START = 2


@dataclass(frozen=True)
class RelatedCase:
    case_id: str
    kind: str
    first_seen: str | None
    # The case this one matched. None means it matched the starting case itself.
    through_case_id: str | None = None
    links_from_start: int = 1
    distances: dict[str, int] = field(default_factory=dict)
    agreeing_features: int | None = None


def query_frames(record: CaseFingerprint) -> list[QueryFrame]:
    return [QueryFrame(None, hashes) for hashes in record.frames]


def related_cases(
    start: CaseFingerprint, others: Iterable[CaseFingerprint], max_links: int = MAX_LINKS_FROM_START
) -> list[RelatedCase]:
    """Find cases joined to ``start`` by at most ``max_links`` matches, oldest first, saying what linked each.

    Local features wrongly match unrelated pairs more often than hashes do, so they only link directly to ``start``.
    """
    pool = {record.case_id: record for record in others if record.case_id != start.case_id}
    found: list[RelatedCase] = []
    queue = [(start, 0)]
    while queue and pool:
        current, links = queue.pop(0)
        if links >= max_links:
            continue
        through = None if links == 0 else current.case_id
        for match in find_matches(current.sha256, query_frames(current), [], list(pool.values())):
            record = pool.pop(match.case_id or "", None)
            if record is None:
                continue
            found.append(RelatedCase(record.case_id, match.kind, match.first_seen, through, links + 1, dict(match.distances)))
            queue.append((record, links + 1))
    for record in pool.values():
        agreeing = best_agreement(start.local_features, record.local_features)
        if agreeing >= MATCH_LIMIT:
            found.append(RelatedCase(record.case_id, SHARES_CONTENT, record.seen_at, agreeing_features=agreeing))
    return sorted(found, key=lambda item: item.first_seen or "")


def add_earlier_matches(result: MediaAnalysisResult, earlier: Sequence[CaseFingerprint]) -> None:
    """Add matches against this owner's earlier cases to a finished analysis. The score is never changed."""
    check = result.checks.fingerprint
    if check is None or check.status.value != "complete":
        return
    check.limitations = [line for line in check.limitations if not line.startswith(NOT_CONFIGURED_PREFIX)]
    check.earlier_cases_checked = max(check.earlier_cases_checked, len(earlier))
    check.compared = check.compared or bool(earlier)
    record = fingerprint_record(result, "this-case", "")
    if record is None or not earlier:
        return
    known = {match.case_id for match in check.matches if match.case_id}
    new = [
        match
        for match in find_matches(record.sha256, query_frames(record), [], earlier)
        if match.case_id not in known
    ]
    check.matches = [*check.matches, *new]
    for match in new:
        kind = "Same file as" if match.kind == EXACT_COPY else "Fingerprints look like the same image as"
        result.evidence.append(f"{kind} earlier case {match.case_id!r}, recorded {match.first_seen}.")
    linked = known | {match.case_id for match in new}
    for other in earlier:
        if other.case_id not in linked and best_agreement(record.local_features, other.local_features) >= MATCH_LIMIT:
            result.evidence.append(
                f"Shares visible content with earlier case {other.case_id!r}, recorded {other.seen_at}. It may be a crop of "
                "the same picture, or the two may only share something like a logo."
            )
