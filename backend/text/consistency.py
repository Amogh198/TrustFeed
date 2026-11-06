"""Flag statements in one submission that conflict, using their context.

A different number alone means little. "50 people were injured" and "200 people
died" do not conflict, and neither do last year's and this year's figures, so two
claims are compared only when they say the same thing about the same event.
A flag asks a person to look. It does not say which statement is wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from backend.text.claims import AnalyzedClaim, content_tokens, is_negated, is_verb_like
from backend.text.entities import WEEKDAYS, NumberMention

SAME_EVENT_SIMILARITY = 0.6
SAME_STATEMENT_SIMILARITY = 0.75
# How far an "about 50" can stretch before a different figure counts as different.
APPROXIMATE_TOLERANCE = 0.15

# These words say a figure moved or belongs to another time, so two figures can both hold.
_CHANGE_WORDS = re.compile(
    r"\b(?:now|later|earlier|previously|initially|originally|formerly|updated|revised|since|then|still|"
    r"rose|risen|rises|fell|fallen|falls|increased|increases|decreased|decreases|grew|grown|dropped|climbed|"
    r"doubled|tripled|compared|versus|vs|from|before|after|yesterday|today|tomorrow|last|next|previous)\b",
    re.IGNORECASE,
)
_GROWTH_WORDS = re.compile(
    r"\b(?:increase|increased|increases|rise|rose|risen|grew|grown|growth|growing|more|higher|up|jump|jumped|surge|surged|"
    r"gain|gained|return|returns|profit|above|over)\b",
    re.IGNORECASE,
)
_FUTURE_WORDS = re.compile(
    r"\b(?:will|shall|would|could|may|might|expected|scheduled|planned|planning|plans|set to|going to|upcoming|"
    r"due|by|until|before|forecast|projected|next|deadline|expires?)\b",
    re.IGNORECASE,
)
# Things that happen to the same subject only once, so two dates cannot both be right.
_ONCE_ONLY = re.compile(
    r"\b(?:died|killed|collapsed|exploded|sank|crashed|assassinated|born|resigned|demolished|destroyed|founded)\b",
    re.IGNORECASE,
)
_PAST_VERB = re.compile(r"\b(?:was|were|happened|occurred|took place|died|[a-z]{3,}ed)\b", re.IGNORECASE)
_PART_OF_WHOLE = re.compile(r"(?<![\w.,])(\d[\d,]*)\s+(?:out\s+)?of\s+(?:the\s+|all\s+|its\s+|their\s+)?(\d[\d,]*)(?![\w,.]*\d)")
_PERCENT_OF = re.compile(r"^\s+of\b", re.IGNORECASE)


@dataclass(frozen=True)
class Inconsistency:
    id: str
    kind: str
    # "conflict" means the claims cannot both stand as written. "note" means they
    # differ but need not be wrong, such as two named sources giving different figures.
    severity: str
    claim_ids: tuple[str, ...]
    explanation: str


def _similarity(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _same_statement(left: AnalyzedClaim, right: AnalyzedClaim, threshold: float) -> bool:
    """True when two claims use the same words for the same action."""
    a, b = content_tokens(left), content_tokens(right)
    if len(a) < 2 or len(b) < 2 or _similarity(a, b) < threshold:
        return False
    # "The fire killed 50" and "The fire injured 200" share most words but report different things.
    return not any(is_verb_like(word) for word in a ^ b)


def _dates_differ(left: AnalyzedClaim, right: AnalyzedClaim) -> bool:
    return any(a.conflicts_with(b) for a in left.dates for b in right.dates)


def _places_differ(left: AnalyzedClaim, right: AnalyzedClaim) -> bool:
    return bool(left.places and right.places and not (left.places & right.places))


def _sources_differ(left: AnalyzedClaim, right: AnalyzedClaim) -> bool:
    return bool(left.attribution and right.attribution and left.attribution != right.attribution)


def _figures_agree(a: NumberMention, b: NumberMention) -> bool:
    """Whether two figures can both be true, allowing for "about", "at least" and "up to"."""
    if a.bound == "at_least" and b.value >= a.value or b.bound == "at_least" and a.value >= b.value:
        return True
    if a.bound == "at_most" and b.value <= a.value or b.bound == "at_most" and a.value <= b.value:
        return True
    if a.bound == "approximate" or b.bound == "approximate":
        return abs(a.value - b.value) <= APPROXIMATE_TOLERANCE * max(abs(a.value), abs(b.value))
    return a.value == b.value


def _conflicting_figures(left: AnalyzedClaim, right: AnalyzedClaim) -> tuple[NumberMention, NumberMention] | None:
    for a in left.numbers:
        matching = [b for b in right.numbers if a.unit and a.unit == b.unit]
        # With several figures in play, one shared figure means they may describe the same thing.
        if matching and not any(_figures_agree(a, b) for b in matching):
            return a, matching[0]
    return None


def _pair_findings(left: AnalyzedClaim, right: AnalyzedClaim) -> list[tuple[str, str, str]]:
    findings: list[tuple[str, str, str]] = []
    moved = bool(_CHANGE_WORDS.search(left.text) or _CHANGE_WORDS.search(right.text))
    severity = "note" if _sources_differ(left, right) else "conflict"
    other_source = (
        f" They name different sources ({left.attribution} and {right.attribution}), so this may be a real disagreement"
        " between them, not an error."
        if severity == "note"
        else ""
    )

    if is_negated(left) != is_negated(right) and _same_statement(left, right, SAME_STATEMENT_SIMILARITY):
        findings.append(("negation", severity, f"One statement says this happened and the other says it did not.{other_source}"))

    if moved or not _same_statement(left, right, SAME_EVENT_SIMILARITY):
        return findings

    figures = None if _dates_differ(left, right) or _places_differ(left, right) else _conflicting_figures(left, right)
    if figures:
        a, b = figures
        findings.append(
            ("figures", severity, f"These describe the same event with different figures: {a.text} and {b.text}.{other_source}")
        )
    # Different figures on different dates read as a series over time, not a conflict.
    if _dates_differ(left, right) and not _places_differ(left, right) and not _conflicting_figures(left, right):
        pair = next((a, b) for a in left.dates for b in right.dates if a.conflicts_with(b))
        # Anything else can simply have happened twice.
        once = _ONCE_ONLY.search(left.text) and _ONCE_ONLY.search(right.text)
        if once:
            findings.append(
                (
                    "dates",
                    severity,
                    f"These describe the same event on different dates: {pair[0].text} and {pair[1].text}.{other_source}",
                )
            )
        else:
            explanation = (
                f"These give different dates, {pair[0].text} and {pair[1].text}, for similar statements. "
                "It may have happened more than once."
            )
            findings.append(("dates", "note", explanation))
    if _places_differ(left, right) and not _dates_differ(left, right):
        places = f"{', '.join(sorted(left.places))} and {', '.join(sorted(right.places))}"
        findings.append(
            (
                "places",
                "note",
                f"These describe the same event in different places: {places}. One place may lie inside the other.",
            )
        )
    return findings


def _claim_findings(claim: AnalyzedClaim, today: date) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for item in claim.dates:
        if item.impossible:
            findings.append(("impossible_date", f"{item.text} is not a date on the calendar."))
            continue
        if item.weekday and item.year and item.month and item.day:
            actual = WEEKDAYS[date(item.year, item.month, item.day).weekday()]
            if actual != item.weekday:
                findings.append(("weekday_mismatch", f"{item.text} was a {actual}, not a {item.weekday}."))
        # Uses the earliest day the stated date could mean, so "in 2026" is not future during 2026.
        if (
            item.year
            and (item.year, item.month or 1, item.day or 1) > (today.year, today.month, today.day)
            and _PAST_VERB.search(claim.text)
            and not _FUTURE_WORDS.search(claim.text)
        ):
            findings.append(
                ("future_date", f"This describes a finished event on {item.text}, after the date of this check ({today.isoformat()}).")
            )
    for number in claim.numbers:
        if (
            number.unit == "%"
            and number.value > 100
            and _PERCENT_OF.match(claim.text[number.end :])
            and not _GROWTH_WORDS.search(claim.text)
        ):
            findings.append(("impossible_share", f"{number.text} of a group is more than the whole group."))
    for match in _PART_OF_WHOLE.finditer(claim.text):
        part, whole = (int(group.replace(",", "")) for group in match.groups())
        if part > whole:
            findings.append(("part_exceeds_whole", f"\"{match.group(0)}\" gives a part larger than its whole."))
    return findings


def find_inconsistencies(claims: list[AnalyzedClaim], *, now: datetime | None = None) -> list[Inconsistency]:
    """Questions, opinions and instructions assert nothing, so they are not compared."""
    today = (now or datetime.now(UTC)).date()
    checkable = [claim for claim in claims if claim.checkable]
    results: list[tuple[str, str, tuple[str, ...], str]] = []
    for claim in checkable:
        results.extend((kind, "conflict", (claim.id,), text) for kind, text in _claim_findings(claim, today))
    for index, left in enumerate(checkable):
        for right in checkable[index + 1 :]:
            results.extend(
                (kind, severity, (left.id, right.id), text) for kind, severity, text in _pair_findings(left, right)
            )
    return [
        Inconsistency(f"inconsistency-{number}", kind, severity, claim_ids, explanation)
        for number, (kind, severity, claim_ids, explanation) in enumerate(results, start=1)
    ]
