"""Small local SQLite store for API case history.

Only rendered analysis results are persisted. Raw uploads are deleted by the
route, and original media files are never saved here.
"""

import os
import sqlite3
from pathlib import Path

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

    def save(self, case: AnalysisResponse) -> None:
        payload = case.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO cases (
                    case_id, created_at, overall_risk, summary, is_replay, replay_label, response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    case.created_at.isoformat(),
                    case.overall_risk.value,
                    case.summary,
                    int(case.is_replay),
                    case.replay_label,
                    payload,
                ),
            )

    def get(self, case_id: str) -> AnalysisResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        return AnalysisResponse.model_validate_json(row["response_json"]) if row else None

    def list(self, limit: int, risk_level: RiskLevel | None = None) -> tuple[list[CaseSummary], int]:
        where = "WHERE overall_risk = ?" if risk_level else ""
        arguments: tuple[object, ...] = (risk_level.value,) if risk_level else ()
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

    def clear(self) -> None:
        """Test helper; production code does not expose a deletion endpoint."""
        with self._connect() as connection:
            connection.execute("DELETE FROM cases")


def default_store() -> CaseStore:
    return CaseStore(os.getenv("CASE_STORE_PATH", "trusttrace.db"))
