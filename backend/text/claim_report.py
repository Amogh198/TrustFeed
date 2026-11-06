"""Bring claim description, the optional entity model and the consistency checks together."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from backend.text.claims import AnalyzedClaim, describe_claim
from backend.text.consistency import Inconsistency, find_inconsistencies
from backend.text.ner import NerRunner, default_runner

MAX_CLAIMS = 20
# Twenty near-identical statements give 190 pairs, which would bury everything else.
MAX_INCONSISTENCIES = 25


@dataclass(frozen=True)
class ClaimsReport:
    claims: list[AnalyzedClaim]
    inconsistencies: list[Inconsistency]
    ner_status: str
    ner_reason: str | None
    omitted_claims: int
    limitations: list[str] = field(default_factory=list)


def analyze_claims(
    units: list[str],
    *,
    runner: NerRunner | None = None,
    now: datetime | None = None,
) -> ClaimsReport:
    """Describe claims already split by ``split_claims``. A model problem is reported, not raised."""
    kept = units[:MAX_CLAIMS]
    claims = [describe_claim(number, text) for number, text in enumerate(kept, start=1)]
    checkable = [claim for claim in claims if claim.checkable]
    outcome = (runner or default_runner()).run([claim.text for claim in checkable])
    if outcome.status == "complete":
        named = {claim.id: found for claim, found in zip(checkable, outcome.entities, strict=True)}
        claims = [
            describe_claim(number, claim.text, named.get(claim.id, ())) for number, claim in enumerate(claims, start=1)
        ]

    limitations = [
        "These checks compare statements within this submission only. They do not show which statement is true.",
        'Numbers written as words, such as "fifty", are not read.',
    ]
    if outcome.status == "unavailable":
        limitations.append(f"Names and places were not extracted, and place conflicts were not checked. {outcome.reason}")
    omitted = len(units) - len(kept)
    if omitted:
        limitations.append(f"Only the first {MAX_CLAIMS} claims were analyzed. {omitted} more were not.")
    inconsistencies = find_inconsistencies(claims, now=now)
    if len(inconsistencies) > MAX_INCONSISTENCIES:
        limitations.append(
            f"Only the first {MAX_INCONSISTENCIES} of {len(inconsistencies)} possible inconsistencies are listed."
        )
    return ClaimsReport(
        claims=claims,
        inconsistencies=inconsistencies[:MAX_INCONSISTENCIES],
        ner_status=outcome.status,
        ner_reason=outcome.reason,
        omitted_claims=omitted,
        limitations=limitations,
    )
