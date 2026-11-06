"""Dashboard accounts: sign-up, sign-in and sessions, using only the standard library.

Passwords are hashed with scrypt, and a session token is stored only as its hash, so a copied
database gives neither. Passwords, tokens and email addresses are never logged. There is no
password reset, because that needs an email service.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

COOKIE_NAME = "trustfeed_session"
SESSION_DAYS = 7
MIN_PASSWORD = 10
MAX_PASSWORD = 200
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "maxmem": 64 * 1024 * 1024, "dklen": 32}
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")
_MAX_FAILURES = 5
_MAX_FAILURES_PER_ADDRESS = 20
_LOCK_SECONDS = 15 * 60
_MAX_TRACKED = 10_000


@dataclass(frozen=True)
class User:
    id: str
    email: str


# Set per request by the middleware in main.py.
CURRENT_USER: ContextVar[User | None] = ContextVar("current_user", default=None)


def current_owner() -> str | None:
    user = CURRENT_USER.get()
    return user.id if user else None


def auth_required() -> bool:
    """Set by whoever runs the server. Off keeps the offline demo working with no account."""
    return os.getenv("AUTH_REQUIRED", "").casefold() in {"1", "true", "yes"}


def signup_enabled() -> bool:
    return os.getenv("AUTH_SIGNUP_ENABLED", "true").casefold() not in {"0", "false", "no"}


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Checked when an address is unknown, so a wrong address takes as long as a wrong password.
_DUMMY_SALT = secrets.token_bytes(16)
_DUMMY_HASH = _hash_password("not a real password", _DUMMY_SALT)


class AuthStore:
    def __init__(self, path: str) -> None:
        self.path = path
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def create_user(self, email: str, password: str) -> User | None:
        """Return the new user, or None when the address is already taken."""
        salt = secrets.token_bytes(16)
        user = User(id=str(uuid4()), email=email)
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO users (id, email, salt, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user.id, email, salt, _hash_password(password, salt), datetime.now(UTC).isoformat()),
                )
        except sqlite3.IntegrityError:
            return None
        return user

    def check_password(self, email: str, password: str) -> User | None:
        with self._connect() as connection:
            row = connection.execute("SELECT id, email, salt, password_hash FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            hmac.compare_digest(_hash_password(password, _DUMMY_SALT), _DUMMY_HASH)
            return None
        if not hmac.compare_digest(_hash_password(password, row["salt"]), row["password_hash"]):
            return None
        return User(id=row["id"], email=row["email"])

    def start_session(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(days=SESSION_DAYS)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE expires_at < ?", (datetime.now(UTC).isoformat(),)
            )
            connection.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (_token_hash(token), user.id, expires.isoformat()),
            )
        return token

    def user_for_token(self, token: str | None) -> User | None:
        if not token:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.email, sessions.expires_at FROM sessions
                JOIN users ON users.id = sessions.user_id WHERE sessions.token_hash = ?
                """,
                (_token_hash(token),),
            ).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) < datetime.now(UTC):
            return None
        return User(id=row["id"], email=row["email"])

    def end_session(self, token: str | None) -> None:
        if token:
            with self._connect() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


class _Throttle:
    """Slow password guessing. Kept in memory, so a restart clears it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, tuple[int, float]] = {}

    def _count(self, key: str, now: float) -> int:
        count, since = self._failures.get(key, (0, now))
        return 0 if now - since > _LOCK_SECONDS else count

    def blocked(self, email: str, address: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return self._count(f"e:{email}", now) >= _MAX_FAILURES or self._count(f"a:{address}", now) >= _MAX_FAILURES_PER_ADDRESS

    def failed(self, email: str, address: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._failures) > _MAX_TRACKED:
                self._failures.clear()
            for key in (f"e:{email}", f"a:{address}"):
                count = self._count(key, now)
                self._failures[key] = (count + 1, self._failures[key][1] if count and key in self._failures else now)

    def passed(self, email: str) -> None:
        with self._lock:
            self._failures.pop(f"e:{email}", None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()


THROTTLE = _Throttle()


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=MAX_PASSWORD)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        value = value.strip().casefold()
        if not _EMAIL.match(value):
            raise ValueError("Enter a valid email address")
        return value


class AccountState(BaseModel):
    email: str | None = None
    auth_required: bool
    signup_enabled: bool


def build_router(store: AuthStore) -> APIRouter:
    router = APIRouter(prefix="/api/auth")

    def begin(response: Response, user: User) -> AccountState:
        response.set_cookie(
            COOKIE_NAME,
            store.start_session(user),
            max_age=SESSION_DAYS * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=os.getenv("AUTH_COOKIE_SECURE", "").casefold() in {"1", "true", "yes"},
            path="/",
        )
        return AccountState(email=user.email, auth_required=auth_required(), signup_enabled=signup_enabled())

    @router.get("/me")
    def me(request: Request) -> AccountState:
        user = store.user_for_token(request.cookies.get(COOKIE_NAME))
        return AccountState(email=user.email if user else None, auth_required=auth_required(), signup_enabled=signup_enabled())

    @router.post("/signup", status_code=201)
    def signup(credentials: Credentials, response: Response) -> AccountState:
        if not signup_enabled():
            raise HTTPException(status_code=403, detail="Sign-up is turned off on this server.")
        if len(credentials.password) < MIN_PASSWORD:
            raise HTTPException(status_code=422, detail=f"Use a password of at least {MIN_PASSWORD} characters.")
        user = store.create_user(credentials.email, credentials.password)
        if user is None:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        return begin(response, user)

    @router.post("/login")
    def login(credentials: Credentials, request: Request, response: Response) -> AccountState:
        address = request.client.host if request.client else "unknown"
        if THROTTLE.blocked(credentials.email, address):
            raise HTTPException(status_code=429, detail="Too many failed tries. Wait 15 minutes, then try again.")
        user = store.check_password(credentials.email, credentials.password)
        if user is None:
            THROTTLE.failed(credentials.email, address)
            raise HTTPException(status_code=401, detail="That email and password don't match.")
        THROTTLE.passed(credentials.email)
        return begin(response, user)

    @router.post("/logout")
    def logout(request: Request, response: Response) -> AccountState:
        store.end_session(request.cookies.get(COOKIE_NAME))
        response.delete_cookie(COOKIE_NAME, path="/")
        return AccountState(auth_required=auth_required(), signup_enabled=signup_enabled())

    return router
