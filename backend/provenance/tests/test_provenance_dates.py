from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.provenance.dates import parse_date, read_page_facts
from backend.provenance.tests.helpers import html_page

HTML = {"content-type": "text/html"}


def facts(body, **headers):
    return read_page_facts({**HTML, **headers}, body)


def test_json_ld_date_is_preferred():
    body = html_page(date_ld="2016-05-23T10:00:00Z", og="2018-01-01T00:00:00Z")
    result = facts(body, **{"last-modified": "Wed, 01 Jan 2020 00:00:00 GMT"})
    assert result.date.observed_at == datetime(2016, 5, 23, 10, tzinfo=timezone.utc)
    assert "JSON-LD" in result.date.evidence


def test_open_graph_is_next():
    result = facts(html_page(og="2018-01-01T05:30:00+05:30"), **{"last-modified": "Wed, 01 Jan 2020 00:00:00 GMT"})
    assert result.date.observed_at == datetime(2018, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert "article:published_time" in result.date.evidence


def test_last_modified_is_the_weakest_hint():
    result = facts(html_page(), **{"last-modified": "Wed, 01 Jan 2020 00:00:00 GMT"})
    assert result.date.observed_at == datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert "weakest" in result.date.evidence


def test_undated_page_has_no_date():
    assert facts(html_page()).date is None


def test_json_ld_graph_and_list_forms():
    block = {
        "@graph": [
            {"@type": "Comment", "datePublished": "2024-01-01"},
            {"@type": ["NewsArticle"], "datePublished": "2019-02-03T04:05:06Z"},
            {"@type": "Comment", "datePublished": "2025-01-01"},
        ]
    }
    body = f'<script type="application/ld+json">{json.dumps([block])}</script>'.encode()
    result = facts(body)
    assert result.date.observed_at.year == 2019
    assert result.is_news_article is True


def test_date_only_values_are_labelled_and_not_given_a_time():
    result = facts(html_page(date_ld="2016-05-23"))
    assert result.date.observed_at == datetime(2016, 5, 23, tzinfo=timezone.utc)
    assert "date only" in result.date.evidence


def test_missing_time_zone_is_stated():
    assert "no time zone" in facts(html_page(date_ld="2016-05-23T10:00:00")).date.evidence


@pytest.mark.parametrize(
    "value",
    ["not a date", "1850-01-01", "yesterday", "", "2016-13-45", "99999999999999999999999999999999999999999999"],
)
def test_unusable_dates_are_rejected(value):
    assert facts(html_page(date_ld=value)).date is None


def test_future_date_is_rejected():
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    assert parse_date(future) is None
    assert facts(html_page(date_ld=future)).date is None


def test_a_bad_json_block_does_not_stop_the_next_one():
    good = json.dumps({"@type": "Article", "datePublished": "2017-01-01"})
    body = f'<script type="application/ld+json">{{broken</script><script type="application/ld+json">{good}</script>'
    assert facts(body.encode()).date.observed_at.year == 2017


def test_deeply_nested_json_does_not_crash():
    body = f'<script type="application/ld+json">{"[" * 100000}</script>'.encode()
    assert facts(body).date is None


def test_binary_garbage_does_not_crash():
    assert facts(bytes(range(256)) * 200).date is None


def test_non_html_only_uses_the_header():
    result = read_page_facts(
        {"content-type": "image/jpeg", "last-modified": "Wed, 01 Jan 2020 00:00:00 GMT"},
        html_page(date_ld="2010-01-01"),
    )
    assert result.date.observed_at.year == 2020


def test_bad_last_modified_is_ignored():
    assert facts(html_page(), **{"last-modified": "whenever"}).date is None


def test_title_is_cleaned():
    result = facts("<title>  Hello‮\n world\x07 </title>".encode())
    assert result.title == "Hello world"
