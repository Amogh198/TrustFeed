"""Link checks, using recorded answers. No test reaches the network."""

import json
from datetime import UTC, datetime

import pytest

from backend.api.app.models import ModuleStatus
from backend.provenance.safe_http import HttpBlocked, HttpFailed, HttpResponse
from backend.text.links import RDAP_URL, find_lookalike, investigate_link, link_checks

NOW = datetime(2026, 11, 6, tzinfo=UTC)
HTML = {"content-type": "text/html; charset=utf-8"}


def page(url, body, status=200, headers=None):
    return HttpResponse(url=url, status=status, headers=headers or HTML, body=body.encode())


def redirect(url, to, status=302):
    return HttpResponse(url=url, status=status, headers={"location": to})


def rdap(domain, registered):
    url = RDAP_URL.format(domain=domain)
    body = json.dumps({"events": [{"eventAction": "registration", "eventDate": registered}]})
    return url, HttpResponse(url=url, status=200, headers={"content-type": "application/rdap+json"}, body=body.encode())


def web(answers):
    """Answer from a table. A request missing from it fails the way a dead site does."""

    def request(url, **_kwargs):
        answer = answers.get(url)
        if answer is None:
            raise HttpFailed("network")
        if isinstance(answer, Exception):
            raise answer
        return answer

    return request


def run(url, answers):
    return investigate_link(url, request=web(answers), now=NOW)


LOGIN = '<title>PayPal: Log in</title><form action="/post"><input type="password" name="p"></form>'


@pytest.mark.parametrize(
    ("host", "brand", "strength"),
    [
        ("paypa1.com", "paypal", "strong"),
        ("xn--pypal-4ve.com", "paypal", "strong"),  # Cyrillic "а"
        ("arnazon.com", "amazon", "strong"),
        ("gooogle.com", "google", "strong"),
        ("paypal.com.evil.example", "paypal", "strong"),
        ("paypal-secure.example", "paypal", "strong"),
        ("sbi-kyc-update.com", "sbi", "strong"),
        ("hdfckyc.com", "hdfc", "strong"),
        ("amazon-rainforest.org", "amazon", "weak"),
        ("amazon.de", "amazon", "weak"),
    ],
)
def test_lookalikes_are_named(host, brand, strength):
    found = find_lookalike(host)
    assert (found.brand, found.strength) == (brand, strength)


@pytest.mark.parametrize(
    "host",
    ["example.org", "maple.com", "paytv.com", "wikipedia.org", "sbicards-news.example.org", "192.0.2.1", "hotpot.com"],
)
def test_ordinary_hosts_are_not_called_lookalikes(host):
    assert find_lookalike(host).brand is None


@pytest.mark.parametrize("host", ["paypal.com", "www.paypal.com", "onlinesbi.sbi", "www.amazon.in"])
def test_a_brands_own_domain_is_recognised(host):
    found = find_lookalike(host)
    assert found.owned_by and found.brand is None


def test_offline_makes_no_request_and_says_why_nothing_ran():
    def refuse(*_args, **_kwargs):
        raise AssertionError("An outside request was made")

    report = investigate_link("https://paypa1.com/a", offline_reason="No consent.", request=refuse)
    assert report.lookalike.brand == "paypal"
    for part in (report.redirects, report.domain, report.page, report.official):
        assert part.status is ModuleStatus.UNAVAILABLE and part.reason == "No consent."
    assert report.assessment == "warning_signs_found"


def test_quiet_offline_link_is_not_called_clean_by_its_parts():
    report = investigate_link("https://example.org/", offline_reason="No consent.")
    assert report.assessment == "none_found"
    assert report.page.asks_for_login is False and report.page.status is ModuleStatus.UNAVAILABLE


def test_redirect_chain_is_walked_and_queries_are_not_kept():
    report = run(
        "https://bit.ly/a",
        {
            "https://bit.ly/a": redirect("https://bit.ly/a", "https://mid.example/x?token=secret"),
            "https://mid.example/x?token=secret": redirect("", "/end?also=secret"),
            "https://mid.example/end?also=secret": page("", "<title>End</title>"),
            **dict([rdap("mid.example", "2010-01-01T00:00:00Z")]),
        },
    )
    assert [hop.host for hop in report.redirects.hops] == ["bit.ly", "mid.example", "mid.example"]
    assert report.redirects.final_host == "mid.example"
    assert "secret" not in report.model_dump_json()
    # Going through a shortener is what a shortener does, so it isn't a sign by itself.
    assert report.signs == []


def test_a_page_refresh_counts_as_a_redirect():
    report = run(
        "https://a.example/",
        {
            "https://a.example/": page("", '<meta http-equiv="refresh" content="0; url=https://b.example/">'),
            "https://b.example/": page("", "<title>B</title>"),
        },
    )
    assert report.redirects.final_host == "b.example"
    assert "redirects_elsewhere" in {sign.sign for sign in report.signs}


def test_redirect_loop_and_endless_chains_leave_the_destination_unknown():
    loop = run("https://a.example/", {"https://a.example/": redirect("", "https://a.example/")})
    assert loop.redirects.status is ModuleStatus.UNAVAILABLE and loop.redirects.final_host is None
    assert "loop" in loop.redirects.reason
    chain = {f"https://a.example/{i}": redirect("", f"https://a.example/{i + 1}") for i in range(20)}
    endless = run("https://a.example/0", chain)
    assert endless.redirects.status is ModuleStatus.UNAVAILABLE and "limit" in endless.redirects.reason


def test_a_blocked_private_redirect_is_reported_and_not_followed():
    report = run(
        "https://a.example/",
        {
            "https://a.example/": redirect("", "http://127.0.0.1/admin"),
            "http://127.0.0.1/admin": HttpBlocked("The address is not on the public internet."),
        },
    )
    assert report.redirects.status is ModuleStatus.UNAVAILABLE
    assert "public internet" in report.redirects.reason
    assert report.page.status is ModuleStatus.UNAVAILABLE


def test_dead_site_is_unavailable_not_clean():
    report = run("https://dead.example/", {})
    assert report.page.status is ModuleStatus.UNAVAILABLE and report.page.reason
    assert report.domain.status is ModuleStatus.UNAVAILABLE and report.domain.reason


def test_new_domain_is_strong_and_young_is_weak():
    url = "https://a.example/"
    new = run(url, {url: page("", "<title>A</title>"), **dict([rdap("a.example", "2026-10-20T00:00:00Z")])})
    assert new.domain.age_days == 17 and new.assessment == "warning_signs_found"
    young = run(url, {url: page("", "<title>A</title>"), **dict([rdap("a.example", "2026-07-01T00:00:00Z")])})
    assert young.assessment == "weak_signs_only"
    old = run(url, {url: page("", "<title>A</title>"), **dict([rdap("a.example", "2001-01-01T00:00:00Z")])})
    assert old.assessment == "none_found" and old.domain.registered_on == "2001-01-01"


@pytest.mark.parametrize(
    "answer",
    [
        HttpResponse(url="", status=404),
        HttpResponse(url="", status=429),
        HttpResponse(url="", status=200, body=b"not json"),
        HttpResponse(url="", status=200, body=b'{"events": "nonsense"}'),
        HttpResponse(url="", status=200, body=b'{"events": [{"eventAction": "registration", "eventDate": "2099-01-01"}]}'),
        HttpFailed("timeout"),
    ],
)
def test_a_bad_registry_answer_is_unavailable_with_a_reason(answer):
    url = "https://a.example/"
    report = run(url, {url: page("", "<title>A</title>"), RDAP_URL.format(domain="a.example"): answer})
    assert report.domain.status is ModuleStatus.UNAVAILABLE and report.domain.reason
    assert report.domain.age_days is None


def test_login_form_on_a_lookalike_is_compared_with_the_official_site():
    url = "https://paypa1.com/"
    report = run(url, {url: page("", LOGIN), "https://paypal.com/": page("", "<title>PayPal: Log in</title><p>Welcome</p>")})
    assert report.page.asks_for_login
    assert report.official.status is ModuleStatus.COMPLETE and report.official.title_similarity == 1.0
    assert {"lookalike_strong", "brand_title_on_form_page", "copies_official_title"} <= {s.sign for s in report.signs}


def test_official_site_failure_is_not_read_as_a_difference():
    url = "https://paypa1.com/"
    report = run(url, {url: page("", LOGIN)})
    assert report.official.status is ModuleStatus.UNAVAILABLE and report.official.title_similarity is None
    assert "paypal.com" in report.official.reason


def test_a_news_story_naming_a_brand_is_not_a_warning():
    url = "https://news.example/story"
    body = "<title>PayPal fined by regulator</title><p>Words about the story.</p>"
    report = run(url, {url: page("", body), **dict([rdap("news.example", "2001-01-01T00:00:00Z")])})
    assert report.assessment == "none_found"
    assert report.official.status is ModuleStatus.NOT_APPLICABLE


def test_a_brands_own_login_page_raises_nothing():
    url = "https://www.paypal.com/signin"
    report = run(url, {url: page("", LOGIN), **dict([rdap("paypal.com", "1999-07-15T00:00:00Z")])})
    assert report.page.asks_for_login and report.assessment == "none_found"


def test_form_fields_are_recognised():
    url = "https://a.example/"
    body = (
        '<form action="https://collect.example/x"><input autocomplete="cc-number">'
        '<input name="otp_code"><input type="hidden" name="cvv"></form>'
    )
    report = run(url, {url: page("", body)})
    assert report.page.asks_for_payment and report.page.asks_for_code and not report.page.asks_for_login
    assert report.page.form_posts_to == ["collect.example"]


def test_password_without_https_is_strong():
    url = "http://a.example/"
    report = run(url, {url: page("", '<input type="password">')})
    assert "sensitive_form_without_https" in {sign.sign for sign in report.signs}


def test_hidden_and_scripted_text_is_ignored_and_title_is_cleaned():
    url = "https://a.example/"
    body = "<title>  Hello\n\x07 there <b>" + "x" * 500 + "</title><script>var a='<input type=password>'</script>"
    report = run(url, {url: page("", body)})
    assert report.page.asks_for_login is False
    assert report.page.title.startswith("Hello there") and len(report.page.title) <= 200
    assert "\x07" not in report.page.title


def test_scripted_page_says_it_may_not_have_been_seen():
    url = "https://a.example/"
    report = run(url, {url: page("", "<div id=root></div><script src=/a.js></script>")})
    assert "scripts" in report.page.reason


def test_a_file_is_not_read_as_a_page():
    url = "https://a.example/f.zip"
    response = HttpResponse(url=url, status=200, headers={"content-type": "application/zip"}, body=b"PK")
    report = run(url, {url: response})
    assert report.page.status is ModuleStatus.NOT_APPLICABLE and "application/zip" in report.page.reason


def test_error_page_is_unavailable():
    url = "https://a.example/"
    report = run(url, {url: page("", "gone", status=404)})
    assert report.page.status is ModuleStatus.UNAVAILABLE and "404" in report.page.reason


def test_time_budget_stops_further_requests():
    calls = []
    ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0])

    def request(url, **_kwargs):
        calls.append(url)
        return page(url, "<title>A</title>")

    report = investigate_link("https://a.example/", request=request, now=NOW, clock=lambda: next(ticks))
    assert calls == ["https://a.example/"]
    assert report.domain.status is ModuleStatus.UNAVAILABLE


def test_every_part_appears_as_a_check_even_when_it_did_not_run():
    report = investigate_link("https://example.org/", offline_reason="No consent.")
    checks = link_checks(report)
    assert {check["check_id"] for check in checks} == {
        "url.lookalike", "url.redirects", "url.domain_age", "url.page", "url.official_site", "url.threat_lists",
    }
    assert all(check["reasoning"] for check in checks)
    assert report.threat_lists.status is ModuleStatus.UNAVAILABLE


# Each of these came from running the check on real sites.
def test_page_title_is_the_first_one_outside_any_drawing():
    url = "https://a.example/"
    body = "<svg><title>Logo</title></svg><title>Real</title><svg><title>Other</title></svg>"
    assert run(url, {url: page("", body)}).page.title == "Real"


def test_moving_between_a_brands_own_domains_is_not_a_sign():
    report = run(
        "https://www.sbi.co.in/",
        {"https://www.sbi.co.in/": redirect("", "https://sbi.bank.in/"), "https://sbi.bank.in/": page("", "<title>SBI</title>")},
    )
    assert report.signs == []


def test_failing_after_a_redirect_still_shows_where_the_link_leads():
    report = run(
        "https://bit.ly/a",
        {"https://bit.ly/a": redirect("", "https://dest.example/"), "https://dest.example/": HttpFailed("too_large")},
    )
    assert report.redirects.final_host == "dest.example"
    assert report.redirects.status is ModuleStatus.UNAVAILABLE and "too large" in report.page.reason


def test_a_word_containing_upi_is_not_a_payment_field():
    url = "https://a.example/"
    assert not run(url, {url: page("", '<input name="occupied">')}).page.asks_for_payment
    assert run(url, {url: page("", '<input name="upi_id">')}).page.asks_for_payment


@pytest.mark.parametrize(("host", "strength"), [("paypa1-login.example.com", "strong"), ("paypal.example.com", "weak")])
def test_subdomains_are_checked(host, strength):
    assert find_lookalike(host).strength == strength
