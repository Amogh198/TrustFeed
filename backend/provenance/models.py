"""Result models, following draft contract v2. Scores stay null: a search proves nothing."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

EARLIEST_CAVEAT = "Earliest appearance these searches found. The true source may be older or elsewhere."
SIMILAR_MEANING = (
    "A similar picture can be a different image of something alike. These results don't show where this image came "
    "from, and they never change the detector score."
)


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
    # For a video, the keyframe that found this page.
    frame_timestamp_s: float | None = None


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

    def to_checks(self) -> list[dict[str, Any]]:
        """Return the explanation check. Its benchmark is null, because search has not been measured."""
        matched = [item for item in self.appearances if item.match_type is not MatchType.SIMILAR]
        exact = sum(item.match_type is MatchType.EXACT for item in matched)
        dated = sum(item.observed_at is not None for item in matched)
        if self.status is not Status.COMPLETE:
            result = "No search result"
        elif not matched:
            result = "No matching pages found"
        else:
            result = f"{len(matched)} pages found, {exact} exact, {dated} with a usable date"
        reasoning = self._evidence()
        if self.status is not Status.COMPLETE:
            reasoning.append("No search result is available, so this check says nothing about where the image appeared.")
        elif not matched:
            reasoning.append("Finding nothing does not show the image is new or unused. Search covers only part of the web.")
        if self.earliest_found:
            reasoning.append(self.earliest_found.caveat)
        return [
            {
                "check_id": "provenance.search",
                "module": "provenance",
                "label": "Where the image was found",
                "status": self.status.value,
                "result": result,
                "reasoning": " ".join(reasoning),
                "benchmark": None,
                "artifacts": [],
                "limitations": list(self.limitations),
            },
            self._similar_check(),
        ]

    def _similar_check(self) -> dict[str, Any]:
        """Similar pictures are reported on their own, because they don't show the image itself was found."""
        similar = [item for item in self.appearances if item.match_type is MatchType.SIMILAR]
        if self.status is not Status.COMPLETE:
            result, reasoning = "No search result", "No search result is available, so nothing is said about similar pictures."
        elif similar:
            count = len(similar)
            result = f"{count} similar {'picture' if count == 1 else 'pictures'} found"
            reasoning = f"The search found pages holding pictures that look similar. {SIMILAR_MEANING}"
        else:
            result = "No similar pictures found"
            reasoning = "No similar pictures were found. Search covers only part of the web, so this shows very little."
        return {
            "check_id": "provenance.similar",
            "module": "provenance",
            "label": "Similar pictures",
            "status": self.status.value,
            "result": result,
            "reasoning": reasoning,
            "benchmark": None,
            "artifacts": [
                {
                    name: value
                    for name, value in {
                        "kind": "similar_match",
                        "label": "similar",
                        "page_url": item.page_url or "",
                        "page_title": item.page_title or "",
                        "domain": item.domain or "",
                        "provider": item.provider,
                    }.items()
                    if value
                }
                for item in similar
            ],
            "limitations": list(self.limitations),
        }

    def timeline_events(self) -> list[dict[str, Any]]:
        """Return one event per appearance. Undated ones stay in, with a null time."""
        return [
            {
                "at": item.observed_at.isoformat().replace("+00:00", "Z") if item.observed_at else None,
                "kind": "web_appearance",
                "label": (
                    f"Similar picture found on {item.domain or 'a page'}"
                    if item.match_type is MatchType.SIMILAR
                    else f"Image found on {item.domain or 'a reference list'}"
                ),
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
        similar = sum(item.match_type is MatchType.SIMILAR for item in self.appearances)
        if similar:
            lines.append(f"{similar} of these are only similar pictures, not shown to be this image.")
        if self.earliest_found:
            earliest = next(i for i in self.appearances if i.id == self.earliest_found.appearance_id)
            lines.append(
                f"Earliest appearance found: {earliest.domain or 'a reference list'} on "
                f"{earliest.observed_at:%Y-%m-%d}. Date evidence: {earliest.date_evidence}"
            )
        else:
            lines.append("None of the appearances has a usable date, so no earliest appearance can be named.")
        return lines
