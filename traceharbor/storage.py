"""SQLite persistence with atomic event and issue updates."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    event_type TEXT NOT NULL,
    level TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    fingerprint TEXT,
    duration_ms REAL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_project_time ON events(project, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_fingerprint ON events(project, fingerprint, timestamp DESC);

CREATE TABLE IF NOT EXISTS issues (
    project TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    title TEXT NOT NULL,
    level TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    latest_event_id TEXT NOT NULL,
    PRIMARY KEY(project, fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_issues_last_seen ON issues(project, last_seen DESC);
"""


class EventStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._lock = Lock()
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def add_event(self, event: dict[str, Any]) -> bool:
        """Persist an event and atomically update its issue. Return False for duplicates."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO events
                    (event_id, project, event_type, level, timestamp, fingerprint, duration_ms, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["project"],
                    event["type"],
                    event["level"],
                    event["timestamp"],
                    event.get("fingerprint"),
                    event.get("duration_ms"),
                    json.dumps(event, sort_keys=True, separators=(",", ":")),
                ),
            )
            if cursor.rowcount == 0:
                return False
            if event.get("fingerprint"):
                connection.execute(
                    """
                    INSERT INTO issues
                        (project, fingerprint, title, level, first_seen, last_seen, event_count, latest_event_id)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(project, fingerprint) DO UPDATE SET
                        title = excluded.title,
                        level = excluded.level,
                        last_seen = MAX(issues.last_seen, excluded.last_seen),
                        event_count = issues.event_count + 1,
                        latest_event_id = CASE
                            WHEN excluded.last_seen >= issues.last_seen THEN excluded.latest_event_id
                            ELSE issues.latest_event_id
                        END
                    """,
                    (
                        event["project"],
                        event["fingerprint"],
                        event["title"],
                        event["level"],
                        event["timestamp"],
                        event["timestamp"],
                        event["event_id"],
                    ),
                )
            return True

    def list_issues(self, project: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT project, fingerprint, title, level, first_seen, last_seen, event_count, latest_event_id
                FROM issues WHERE project = ? ORDER BY last_seen DESC LIMIT ?
                """,
                (project, min(max(limit, 1), 200)),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_issue(self, project: str, fingerprint: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            issue = connection.execute(
                "SELECT * FROM issues WHERE project = ? AND fingerprint = ?",
                (project, fingerprint),
            ).fetchone()
            if issue is None:
                return None
            events = connection.execute(
                """
                SELECT payload_json FROM events
                WHERE project = ? AND fingerprint = ? ORDER BY timestamp DESC LIMIT 20
                """,
                (project, fingerprint),
            ).fetchall()
        result = dict(issue)
        result["events"] = [json.loads(row["payload_json"]) for row in events]
        return result

    def metrics(self, project: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS event_count,
                    SUM(CASE WHEN event_type = 'error' THEN 1 ELSE 0 END) AS error_count,
                    SUM(CASE WHEN event_type = 'transaction' THEN 1 ELSE 0 END) AS transaction_count,
                    AVG(CASE WHEN event_type = 'transaction' THEN duration_ms END) AS avg_duration_ms
                FROM events WHERE project = ?
                """,
                (project,),
            ).fetchone()
            issue_count = connection.execute(
                "SELECT COUNT(*) FROM issues WHERE project = ?", (project,)
            ).fetchone()[0]
        return {
            "event_count": int(row["event_count"] or 0),
            "error_count": int(row["error_count"] or 0),
            "transaction_count": int(row["transaction_count"] or 0),
            "issue_count": int(issue_count),
            "avg_duration_ms": round(float(row["avg_duration_ms"] or 0.0), 2),
        }
