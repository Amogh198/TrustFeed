"""Result models, following draft contract v2. Scores stay null: a search proves nothing."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

EARLIEST_CAVEAT = "Earliest appearance these searches found. The true source may be older or elsewhere."


class Status(StrEnum):
    COMPLETE = "complete"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class MatchType(StrEnum):
    EXACT = "exact"
    PARTIAL = "partial"
    SIMILAR = "similar"


class Platform(StrEnum):
    NEWS = "news"
    SOCIAL = "social"
    WEB = "web"
    UNKNOWN = "unknown"


class DateSource(StrEnum):
    PAGE_METADATA = "page_metadata"
    CRAWL_DATE = "crawl_date"
    SOCIAL_POST = "social_post"
    # Added to the draft contract: the team's own pHash reference list.
    REFERENCE_INDEX = "reference_index"
    NONE = "none"


class ProviderRun(BaseModel):
    name: str
    status: Status
    result_count: int = 0
    limitation: str | None = None


class Appearance(BaseModel):
    id: str
    page_url: str | None = None
    page_title: str | None = None
    domain: str | None = None
    platform: Platform = Platform.UNKNOWN
    image_url: str | None = None
    match_type: MatchType
    phash_distance: int | None = None
    observed_at: datetime | None = None
    date_source: DateSource = DateSource.NONE
    date_evidence: str | None = None
    provider: str


class EarliestFound(BaseModel):
    appearance_id: str
    observed_at: datetime
    date_source: DateSource
    caveat: str = EARLIEST_CAVEAT


class ProvenanceReport(BaseModel):
    case_id: str | None = None
    status: Status
    searched_at: datetime | None = None
    replay: bool = False
    # True for invented demo data. The dashboard must say so.
    synthetic: bool = False
    media_sha256: str | None = None
    phash: str | None = None
    providers: list[ProviderRun] = Field(default_factory=list)
    earliest_found: EarliestFound | None = None
    appearances: list[Appearance] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    def for_case(self, case_id: str) -> ProvenanceReport:
        return self.model_copy(update={"case_id": case_id})

    def to_module_result(self) -> dict[str, Any]:
        """Return the shared ``ModuleResult`` shape. The score is always null."""
        return {
            "status": self.status.value,
            "score": None,
            "confidence": None,
            "evidence": self._evidence(),
            "limitations": list(self.limitations),
        }

    def timeline_events(self) -> list[dict[str, Any]]:
        """Return one event per appearance. Undated ones stay in, with a null time."""
        return [
            {
                "at": item.observed_at.isoformat().replace("+00:00", "Z") if item.observed_at else None,
                "kind": "web_appearance",
                "label": f"Image found on {item.domain or 'a reference list'}",
                "module": "provenance",
                "ref": item.id,
                "date_source": item.date_source.value,
                "synthetic": self.synthetic,
            }
            for item in self.appearances
        ]

    def _evidence(self) -> list[str]:
        lines: list[str] = []
        if self.synthetic:
            lines.append("SYNTHETIC DEMO DATA: these pages and dates are invented.")
        elif self.replay:
            lines.append("REPLAY: these results were recorded earlier, not searched live.")
        if self.status is not Status.COMPLETE:
            return lines
        searched = [run.name for run in self.providers if run.status is Status.COMPLETE]
        if not self.appearances:
            lines.append(f"No matching pages were found. Searched: {', '.join(searched) or 'none'}.")
            return lines
        exact = sum(item.match_type is MatchType.EXACT for item in self.appearances)
        dated = sum(item.observed_at is not None for item in self.appearances)
        lines.append(
            f"Found {len(self.appearances)} appearances ({exact} exact), {dated} with a usable date. "
            f"Searched: {', '.join(searched)}."
        )
        if self.earliest_found:
            earliest = next(i for i in self.appearances if i.id == self.earliest_found.appearance_id)
            lines.append(
                f"Earliest appearance found: {earliest.domain or 'a reference list'} on "
                f"{earliest.observed_at:%Y-%m-%d}. Date evidence: {earliest.date_evidence}"
            )
        else:
            lines.append("None of the appearances has a usable date, so no earliest appearance can be named.")
        return lines
