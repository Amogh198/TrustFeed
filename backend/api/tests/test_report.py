"""Investigation report, PDF export, search and overview."""

import pytest
from fastapi.testclient import TestClient

from backend.api.app.main import CASE_STORE, CASES, app
from backend.api.app.report import _pdf_text, render_pdf

client = TestClient(app)
SCAM = "Pay a registration fee of Rs 500 to get this work from home job. Send your OTP now to claim your prize."


@pytest.fixture(autouse=True)
def fresh():
    CASES.clear()
    CASE_STORE.clear()


def make(**body):
    return client.post("/api/cases/analyze", json=body).json()


def test_report_separates_the_four_kinds_and_says_what_did_not_run():
    case = make(text=SCAM, url="https://paypa1.com/a")
    report = client.get(f"/api/cases/{case['case_id']}/report").json()
    assert report["investigation_id"] == case["case_id"]
    assert set(report["findings"]) == {"manipulated_media", "misleading_context", "false_claims", "scams"}
    assert report["findings"]["scams"]["status"] == "signs_found"
    assert report["findings"]["manipulated_media"]["status"] == "not_checked"
    assert report["findings"]["false_claims"]["status"] == "not_checked"
    assert report["earlier_appearances"]["status"] == "not_checked"
    assert report["spread"]["status"] == "not_checked"
    assert report["recommended_actions"] and report["uncertain"]
    assert any(item["kind"] == "reputation" and item["status"] == "unavailable" for item in report["sources_consulted"])


def test_report_on_a_synthetic_replay_is_labelled():
    scenario = client.get("/api/replay/scenarios").json()["scenarios"][0]["id"]
    case = client.post(f"/api/replay/{scenario}/start").json()
    report = client.get(f"/api/cases/{case['case_id']}/report").json()
    assert report["replay_label"]
    pdf = client.get(f"/api/cases/{case['case_id']}/report.pdf").content
    assert b"REPLAY" in pdf


def test_pdf_download_is_a_valid_looking_pdf():
    case = make(text=SCAM + " (brackets) back\\slash and हिन्दी text.")
    response = client.get(f"/api/cases/{case['case_id']}/report.pdf")
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    body = response.content
    assert body.startswith(b"%PDF-1.4") and body.rstrip().endswith(b"%%EOF")
    # The cross-reference table must point at the real position of each object.
    start = int(body.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    assert body[start:start + 4] == b"xref"
    entries = body[start:].split(b"\n")[3:]
    assert body[int(entries[0][:10]):].startswith(b"1 0 obj")


def test_long_report_flows_onto_more_pages():
    report = client.get(f"/api/cases/{make(text=SCAM)['case_id']}/report").json()
    report["uncertain"] = ["A line of text. " * 40] * 60
    body = render_pdf(report)
    assert body.count(b"/Type /Page ") > 1


def test_unknown_case_is_404():
    assert client.get("/api/cases/nope/report").status_code == 404
    assert client.get("/api/cases/nope/report.pdf").status_code == 404


def test_search_and_filters():
    scam = make(text=SCAM)
    link = make(url="https://paypa1.com/a")
    plain = make(text="The library opens at nine on weekdays.")
    found = lambda **params: {item["case_id"] for item in client.get("/api/cases", params=params).json()["cases"]}  # noqa: E731
    assert found() == {scam["case_id"], link["case_id"], plain["case_id"]}
    assert found(q="library") == {plain["case_id"]}
    assert found(q=link["case_id"][:8]) == {link["case_id"]}
    assert found(q="100%_nothing") == set()
    assert found(kind="link") == {link["case_id"]}
    assert found(kind="scam") == {scam["case_id"]}
    assert client.get("/api/cases", params={"kind": "nonsense"}).status_code == 422
    assert client.get("/api/cases", params={"q": "library"}).json()["total"] == 1


def test_overview_counts_and_keeps_replays_apart():
    make(text=SCAM, url="https://paypa1.com/a")
    make(text="The library opens at nine on weekdays.")
    scenario = client.get("/api/replay/scenarios").json()["scenarios"][0]["id"]
    client.post(f"/api/replay/{scenario}/start")
    overview = client.get("/api/overview").json()
    assert overview["investigations"] == 2 and overview["replays"] == 1
    assert sum(overview["risk_distribution"].values()) == 2
    assert overview["suspicious_urls"][0]["host"] == "paypa1.com"
    assert overview["recent_high_risk"][0]["level"] == "critical"
    assert overview["claims_to_verify"]


def test_overview_with_nothing_saved_is_empty_not_invented():
    overview = client.get("/api/overview").json()
    assert overview["investigations"] == 0 and overview["recent_high_risk"] == []


def test_pdf_text_is_escaped_and_never_breaks_the_file():
    assert _pdf_text("a (b) c\x07") == r"a \(b\) c "
    backslash = chr(92)
    assert _pdf_text(f"back{backslash}slash") == f"back{backslash * 2}slash"
    assert set(_pdf_text("हिन्दी")) == {"?"}
