"""Small local SQLite store for API case history.

Only rendered analysis results are persisted. Raw uploads are deleted by the
route, and original media files are never saved here. A traced case's details
include public account handles and post links, so this file stays out of Git.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from backend.api.app.models import AnalysisResponse, CaseSummary, RiskLevel


class CaseStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    overall_risk TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    is_replay INTEGER NOT NULL,
                    replay_label TEXT,
                    response_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS cases_created_at_idx ON cases (created_at DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS case_details (
                    case_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    PRIMARY KEY (case_id, kind)
                )
                """
            )
            # Databases from before accounts get the column, and their cases stay unowned.
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(cases)")}
            if "owner_id" not in columns:
                connection.execute("ALTER TABLE cases ADD COLUMN owner_id TEXT")

    def save(self, case: AnalysisResponse, owner_id: str | None = None) -> None:
        payload = case.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO cases (
                    case_id, created_at, overall_risk, summary, is_replay, replay_label, response_json, owner_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    case.created_at.isoformat(),
                    case.overall_risk.value,
                    case.summary,
                    int(case.is_replay),
                    case.replay_label,
                    payload,
                    owner_id,
                ),
            )

    def owner_of(self, case_id: str) -> tuple[bool, str | None]:
        """Say whether a case is saved, and who owns it. A null owner means it was saved signed out."""
        with self._connect() as connection:
            row = connection.execute("SELECT owner_id FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return (True, row["owner_id"]) if row else (False, None)

    def get(self, case_id: str) -> AnalysisResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        return AnalysisResponse.model_validate_json(row["response_json"]) if row else None

    def save_detail(self, case_id: str, kind: str, detail: dict[str, Any]) -> None:
        """Keep a module's full result, such as a source search, beside the case."""
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO case_details (case_id, kind, detail_json) VALUES (?, ?, ?)",
                (case_id, kind, json.dumps(detail)),
            )

    def get_detail(self, case_id: str, kind: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT detail_json FROM case_details WHERE case_id = ? AND kind = ?", (case_id, kind)
            ).fetchone()
        return json.loads(row["detail_json"]) if row else None

    def list(
        self, limit: int, risk_level: RiskLevel | None = None, owner_id: str | None = None
    ) -> tuple[list[CaseSummary], int]:
        """List one owner's cases. No owner means the cases saved while signed out."""
        where = "WHERE owner_id IS ?" + (" AND overall_risk = ?" if risk_level else "")
        arguments: tuple[object, ...] = (owner_id, risk_level.value) if risk_level else (owner_id,)
        with self._connect() as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM cases {where}", arguments).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT case_id, created_at, overall_risk, summary, is_replay, replay_label
                FROM cases {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*arguments, limit),
            ).fetchall()
        return (
            [
                CaseSummary(
                    case_id=row["case_id"],
                    created_at=row["created_at"],
                    overall_risk=row["overall_risk"],
                    summary=row["summary"],
                    is_replay=bool(row["is_replay"]),
                    replay_label=row["replay_label"],
                )
                for row in rows
            ],
            total,
        )

    def recent(self, limit: int, owner_id: str | None = None) -> "list[AnalysisResponse]":
        """Return one owner's whole cases, newest first, for search and the overview."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT response_json FROM cases WHERE owner_id IS ? ORDER BY created_at DESC LIMIT ?", (owner_id, limit)
            ).fetchall()
        return [AnalysisResponse.model_validate_json(row["response_json"]) for row in rows]

    def clear(self) -> None:
        """Test helper; production code does not expose a deletion endpoint."""
        with self._connect() as connection:
            connection.execute("DELETE FROM cases")
            connection.execute("DELETE FROM case_details")


def default_store() -> CaseStore:
    return CaseStore(os.getenv("CASE_STORE_PATH", "trustfeed.db"))
