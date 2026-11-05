"""The provenance explanation check."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from backend.provenance.models import (
    EARLIEST_CAVEAT,
    Appearance,
    DateSource,
    EarliestFound,
    MatchType,
    ProvenanceReport,
    ProviderRun,
    Status,
)


def appearance(identifier, match=MatchType.EXACT, observed=None):
    return Appearance(
        id=identifier,
        page_url=f"https://site.test/{identifier}",
        domain="site.test",
        match_type=match,
        observed_at=observed,
        date_source=DateSource.PAGE_METADATA if observed else DateSource.NONE,
        date_evidence="page metadata" if observed else None,
        provider="fake_provider",
    )


def found_report(**fields):
    when = datetime(2020, 1, 2, tzinfo=UTC)
    return ProvenanceReport(
        status=Status.COMPLETE,
        providers=[ProviderRun(name="fake_provider", status=Status.COMPLETE, result_count=2)],
        appearances=[appearance("a", observed=when), appearance("b", MatchType.SIMILAR)],
        earliest_found=EarliestFound(appearance_id="a", observed_at=when, date_source=DateSource.PAGE_METADATA),
        limitations=["Search covers only part of the web."],
        **fields,
    )


def test_found_pages_are_counted_and_keep_the_earliest_caveat():
    check, similar = found_report().to_checks()
    assert check["check_id"] == "provenance.search"
    assert check["module"] == "provenance"
    assert check["status"] == "complete"
    # The similar picture is counted in its own check, not here.
    assert check["result"] == "1 pages found, 1 exact, 1 with a usable date"
    assert similar["result"] == "1 similar picture found"
    assert EARLIEST_CAVEAT in check["reasoning"]
    assert check["limitations"] == ["Search covers only part of the web."]
    json.dumps(check)


def test_search_accuracy_is_not_claimed():
    assert found_report().to_checks()[0]["benchmark"] is None


def test_never_calls_anything_the_source():
    reasoning = found_report().to_checks()[0]["reasoning"].lower()
    assert "the original" not in reasoning
    assert "is the source" not in reasoning
    assert "true source may be older" in reasoning


def test_finding_nothing_is_not_called_evidence():
    report = ProvenanceReport(
        status=Status.COMPLETE, providers=[ProviderRun(name="fake_provider", status=Status.COMPLETE)]
    )
    check, _similar = report.to_checks()
    assert check["result"] == "No matching pages found"
    assert "does not show the image is new or unused" in check["reasoning"]


def test_unavailable_search_says_nothing_was_learned():
    check, _similar = ProvenanceReport(status=Status.UNAVAILABLE, limitations=["no key"]).to_checks()
    assert check["status"] == "unavailable"
    assert check["result"] == "No search result"
    assert "says nothing about where the image appeared" in check["reasoning"]
    assert check["limitations"] == ["no key"]


def test_synthetic_and_replayed_data_stay_labelled():
    assert "SYNTHETIC DEMO DATA" in found_report(synthetic=True).to_checks()[0]["reasoning"]
    assert "REPLAY" in found_report(replay=True).to_checks()[0]["reasoning"]
