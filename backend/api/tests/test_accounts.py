"""Accounts: sign-in, sessions, and who can read which case."""

import logging
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.api.app.auth import COOKIE_NAME, THROTTLE
from backend.api.app.main import CASE_STORE, CASES, app

# Test values only, for the throwaway test database.
PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("AUTH_SIGNUP_ENABLED", raising=False)
    CASES.clear()
    CASE_STORE.clear()
    THROTTLE.clear()


def email():
    return f"{uuid4().hex}@example.test"


def signed_in():
    client = TestClient(app)
    assert client.post("/api/auth/signup", json={"email": email(), "password": PASSWORD}).status_code == 201
    return client


def make(client, text="The library opens at nine on weekdays."):
    return client.post("/api/cases/analyze", json={"text": text}).json()["case_id"]


def test_signup_signs_in_and_logout_ends_the_session():
    client = TestClient(app)
    address = email()
    body = client.post("/api/auth/signup", json={"email": address.upper(), "password": PASSWORD}).json()
    assert body["email"] == address
    assert client.get("/api/auth/me").json()["email"] == address
    token = client.cookies[COOKIE_NAME]
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").json()["email"] is None
    # The old token is dead on the server too, not just removed from the browser.
    other = TestClient(app, cookies={COOKIE_NAME: token})
    assert other.get("/api/auth/me").json()["email"] is None


def test_cookie_is_http_only_and_same_site():
    client = TestClient(app)
    response = client.post("/api/auth/signup", json={"email": email(), "password": PASSWORD})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_nothing_secret_is_stored_in_the_clear():
    client = TestClient(app)
    address = email()
    client.post("/api/auth/signup", json={"email": address, "password": PASSWORD})
    token = client.cookies[COOKIE_NAME]
    with sqlite3.connect(CASE_STORE.path) as connection:
        user = connection.execute("SELECT password_hash, salt FROM users WHERE email = ?", (address,)).fetchone()
        tokens = [row[0] for row in connection.execute("SELECT token_hash FROM sessions")]
    assert PASSWORD.encode() not in user[0] and len(user[1]) == 16
    assert token not in tokens


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"email": "not-an-email", "password": PASSWORD}, 422),
        ({"email": "a@example.test", "password": "short"}, 422),
        ({"email": "a@example.test", "password": "x" * 201}, 422),
    ],
)
def test_bad_signups_are_refused(body, status):
    assert TestClient(app).post("/api/auth/signup", json=body).status_code == status


def test_duplicate_email_is_refused():
    address = email()
    assert TestClient(app).post("/api/auth/signup", json={"email": address, "password": PASSWORD}).status_code == 201
    assert TestClient(app).post("/api/auth/signup", json={"email": address, "password": PASSWORD}).status_code == 409


def test_signup_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("AUTH_SIGNUP_ENABLED", "false")
    assert TestClient(app).post("/api/auth/signup", json={"email": email(), "password": PASSWORD}).status_code == 403


def test_wrong_password_and_unknown_email_read_the_same():
    address = email()
    TestClient(app).post("/api/auth/signup", json={"email": address, "password": PASSWORD})
    wrong = TestClient(app).post("/api/auth/login", json={"email": address, "password": "wrong password here"})
    unknown = TestClient(app).post("/api/auth/login", json={"email": email(), "password": "wrong password here"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    right = TestClient(app).post("/api/auth/login", json={"email": address, "password": PASSWORD})
    assert right.status_code == 200 and COOKIE_NAME in right.cookies


def test_guessing_is_slowed_down_even_with_the_right_password():
    address = email()
    TestClient(app).post("/api/auth/signup", json={"email": address, "password": PASSWORD})
    for _ in range(5):
        assert TestClient(app).post("/api/auth/login", json={"email": address, "password": "wrong password"}).status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"email": address, "password": PASSWORD}).status_code == 429


def test_another_persons_case_looks_like_it_does_not_exist():
    owner, other = signed_in(), signed_in()
    case_id = make(owner)
    missing = other.get("/api/cases/no-such-case")
    for path in (
        f"/api/cases/{case_id}",
        f"/api/cases/{case_id}/export",
        f"/api/cases/{case_id}/report",
        f"/api/cases/{case_id}/report.pdf",
        f"/api/cases/{case_id}/explanation",
        f"/api/cases/{case_id}/timeline",
        f"/api/cases/{case_id}/provenance",
        f"/api/network/{case_id}",
        f"/api/network/{case_id}/coverage",
        f"/api/network/{case_id}/tests",
    ):
        assert owner.get(path).status_code == 200, path
        refused = other.get(path)
        assert refused.status_code == 404, path
        assert refused.json() == missing.json(), path
        assert TestClient(app).get(path).status_code == 404, path
    assert other.post(f"/api/cases/{case_id}/action-packet", json={"audience": "reviewers"}).status_code == 404


def test_lists_search_and_overview_show_only_your_own():
    owner, other = signed_in(), signed_in()
    mine = make(owner, "Only the owner wrote this harbour sentence.")
    theirs = make(other, "Somebody else wrote this meadow sentence.")
    anonymous = make(TestClient(app), "Nobody signed in for this orchard sentence.")
    ids = lambda client, **params: {c["case_id"] for c in client.get("/api/cases", params=params).json()["cases"]}  # noqa: E731
    assert ids(owner) == {mine} and ids(other) == {theirs} and ids(TestClient(app)) == {anonymous}
    assert ids(owner, q="meadow") == set() and ids(owner, q="harbour") == {mine}
    assert ids(owner, kind="text") == {mine}
    assert owner.get("/api/overview").json()["investigations"] == 1
    assert TestClient(app).get("/api/overview").json()["investigations"] == 1


def test_without_required_sign_in_the_demo_still_works_with_no_account():
    client = TestClient(app)
    assert client.get("/api/cases/demo-001").status_code == 200
    assert client.get("/api/cases/demo-story-001/report").status_code == 200
    assert client.post("/api/cases/analyze", json={"text": "Hello there everyone."}).status_code == 200
    assert signed_in().get("/api/cases/demo-001").status_code == 200


def test_required_sign_in_blocks_everything_but_sign_in(monkeypatch):
    client = signed_in()
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    anonymous = TestClient(app)
    for method, path in (("get", "/api/cases"), ("get", "/api/overview"), ("get", "/api/cases/demo-001"), ("get", "/api/monitors")):
        assert getattr(anonymous, method)(path).status_code == 401, path
    assert anonymous.post("/api/cases/analyze", json={"text": "Hello there everyone."}).status_code == 401
    assert anonymous.get("/health").status_code == 200
    assert anonymous.get("/api/auth/me").json() == {"email": None, "auth_required": True, "signup_enabled": True}
    assert client.get("/api/cases").status_code == 200
    assert anonymous.get("/docs").status_code == 401 and anonymous.get("/openapi.json").status_code == 401


def test_a_forged_or_expired_cookie_counts_as_signed_out(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    assert TestClient(app, cookies={COOKIE_NAME: "forged"}).get("/api/cases").status_code == 401
    client = signed_in()
    with sqlite3.connect(CASE_STORE.path) as connection:
        connection.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
    assert client.get("/api/cases").status_code == 401


def test_requests_from_another_site_carrying_a_session_are_refused():
    client = signed_in()
    evil = {"Origin": "https://evil.example"}
    assert client.post("/api/cases/analyze", json={"text": "Hello there."}, headers=evil).status_code == 403
    assert client.post("/api/auth/logout", headers=evil).status_code == 403
    assert TestClient(app).post("/api/auth/login", json={"email": email(), "password": PASSWORD}, headers=evil).status_code == 403
    good = {"Origin": "http://localhost:5173"}
    response = client.post("/api/cases/analyze", json={"text": "Hello there."}, headers=good)
    assert response.status_code == 200 and response.headers["access-control-allow-credentials"] == "true"


def test_passwords_never_reach_the_logs(caplog):
    with caplog.at_level(logging.DEBUG):
        address = email()
        TestClient(app).post("/api/auth/signup", json={"email": address, "password": PASSWORD})
        TestClient(app).post("/api/auth/login", json={"email": address, "password": PASSWORD})
    assert PASSWORD not in caplog.text


def test_a_database_from_before_accounts_is_upgraded_and_stays_readable(tmp_path):
    from backend.api.app.store import CaseStore

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE cases (case_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, overall_risk TEXT NOT NULL, "
            "summary TEXT NOT NULL, is_replay INTEGER NOT NULL, replay_label TEXT, response_json TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO cases VALUES ('old', '2026-01-01T00:00:00+00:00', 'low', 's', 0, NULL, '{}')")
    store = CaseStore(path)
    assert store.owner_of("old") == (True, None)
    assert store.list(limit=5)[1] == 1 and store.list(limit=5, owner_id="someone")[1] == 0
