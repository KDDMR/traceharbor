"""Durable build-analysis jobs and snapshot-diff persistence."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

ARTIFACT_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifact_builds (
    build_id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    object_key TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL,
    baseline_build_id TEXT,
    status TEXT NOT NULL,
    summary_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project, idempotency_key),
    FOREIGN KEY(baseline_build_id) REFERENCES artifact_builds(build_id)
);
CREATE INDEX IF NOT EXISTS idx_artifact_builds_project_created
    ON artifact_builds(project, created_at DESC);

CREATE TABLE IF NOT EXISTS analysis_jobs (
    job_id TEXT PRIMARY KEY,
    build_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    available_at REAL NOT NULL,
    lease_owner TEXT,
    lease_expires_at REAL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(build_id) REFERENCES artifact_builds(build_id)
);
CREATE INDEX IF NOT EXISTS idx_analysis_jobs_claim
    ON analysis_jobs(status, available_at, lease_expires_at);

CREATE TABLE IF NOT EXISTS snapshot_diffs (
    build_id TEXT NOT NULL,
    path TEXT NOT NULL,
    status TEXT NOT NULL,
    difference_ratio REAL NOT NULL,
    baseline_sha256 TEXT,
    current_sha256 TEXT,
    width INTEGER,
    height INTEGER,
    PRIMARY KEY(build_id, path),
    FOREIGN KEY(build_id) REFERENCES artifact_builds(build_id) ON DELETE CASCADE
);
"""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _decode_build(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    raw_summary = result.pop("summary_json", None)
    result["summary"] = json.loads(raw_summary) if raw_summary else None
    return result


class ArtifactRepository:
    """SQLite-backed queue with atomic claiming, leases and bounded retries."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._write_lock = Lock()
        with self._connect() as connection:
            connection.executescript(ARTIFACT_SCHEMA)

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

    def find_by_idempotency(self, project: str, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT b.*, j.job_id, j.status AS job_status
                FROM artifact_builds b JOIN analysis_jobs j USING(build_id)
                WHERE b.project = ? AND b.idempotency_key = ?
                """,
                (project, idempotency_key),
            ).fetchone()
        return _decode_build(row)

    def create_submission(
        self,
        *,
        build_id: str,
        job_id: str,
        project: str,
        object_key: str,
        sha256: str,
        size_bytes: int,
        idempotency_key: str,
        baseline_build_id: str | None,
        max_attempts: int,
    ) -> tuple[dict[str, Any], bool]:
        """Create a build and job together, or return an idempotent replay."""
        with self._write_lock, self._connect() as connection:
            existing = connection.execute(
                """
                SELECT b.*, j.job_id, j.status AS job_status
                FROM artifact_builds b JOIN analysis_jobs j USING(build_id)
                WHERE b.project = ? AND b.idempotency_key = ?
                """,
                (project, idempotency_key),
            ).fetchone()
            if existing is not None:
                decoded = _decode_build(existing)
                assert decoded is not None
                return decoded, True

            now = _utc_now()
            connection.execute(
                """
                INSERT INTO artifact_builds
                    (build_id, project, object_key, sha256, size_bytes, idempotency_key,
                     baseline_build_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    build_id,
                    project,
                    object_key,
                    sha256,
                    size_bytes,
                    idempotency_key,
                    baseline_build_id,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO analysis_jobs
                    (job_id, build_id, status, attempts, max_attempts, available_at,
                     created_at, updated_at)
                VALUES (?, ?, 'queued', 0, ?, ?, ?, ?)
                """,
                (job_id, build_id, max_attempts, time.time(), now, now),
            )
        created = self.get_build(build_id)
        assert created is not None
        created["job_id"] = job_id
        created["job_status"] = "queued"
        return created, False

    def claim_job(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        now_epoch = time.time()
        now = _utc_now()
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM analysis_jobs
                WHERE (status = 'queued' AND available_at <= ?)
                   OR (status = 'running' AND lease_expires_at <= ?)
                ORDER BY available_at, created_at
                LIMIT 1
                """,
                (now_epoch, now_epoch),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status = 'running', attempts = attempts + 1, lease_owner = ?,
                    lease_expires_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (worker_id, now_epoch + lease_seconds, now, row["job_id"]),
            )
            connection.execute(
                "UPDATE artifact_builds SET status = 'running', updated_at = ? WHERE build_id = ?",
                (now, row["build_id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM analysis_jobs WHERE job_id = ?", (row["job_id"],)
            ).fetchone()
        return dict(claimed) if claimed else None

    def complete_job(
        self,
        job_id: str,
        worker_id: str,
        summary: dict[str, Any],
        diffs: list[dict[str, Any]],
    ) -> bool:
        now = _utc_now()
        with self._write_lock, self._connect() as connection:
            job = connection.execute(
                "SELECT build_id, status, lease_owner FROM analysis_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if job is None:
                raise KeyError("analysis job does not exist")
            if job["status"] != "running" or job["lease_owner"] != worker_id:
                return False
            build_id = job["build_id"]
            connection.execute("DELETE FROM snapshot_diffs WHERE build_id = ?", (build_id,))
            connection.executemany(
                """
                INSERT INTO snapshot_diffs
                    (build_id, path, status, difference_ratio, baseline_sha256,
                     current_sha256, width, height)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        build_id,
                        item["path"],
                        item["status"],
                        item["difference_ratio"],
                        item.get("baseline_sha256"),
                        item.get("current_sha256"),
                        item.get("width"),
                        item.get("height"),
                    )
                    for item in diffs
                ],
            )
            connection.execute(
                """
                UPDATE artifact_builds
                SET status = 'completed', summary_json = ?, updated_at = ?
                WHERE build_id = ?
                """,
                (json.dumps(summary, sort_keys=True), now, build_id),
            )
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status = 'completed', lease_owner = NULL, lease_expires_at = NULL,
                    last_error = NULL, updated_at = ?
                WHERE job_id = ?
                """,
                (now, job_id),
            )
        return True

    def fail_job(
        self,
        job_id: str,
        worker_id: str,
        error: str,
        retryable: bool,
        retry_delay: float,
    ) -> str:
        now = _utc_now()
        with self._write_lock, self._connect() as connection:
            job = connection.execute(
                """
                SELECT build_id, attempts, max_attempts, status, lease_owner
                FROM analysis_jobs WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if job is None:
                raise KeyError("analysis job does not exist")
            if job["status"] != "running" or job["lease_owner"] != worker_id:
                return job["status"]
            should_retry = retryable and job["attempts"] < job["max_attempts"]
            status = "queued" if should_retry else "failed"
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status = ?, available_at = ?, lease_owner = NULL,
                    lease_expires_at = NULL, last_error = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status, time.time() + retry_delay, error[:2_000], now, job_id),
            )
            connection.execute(
                "UPDATE artifact_builds SET status = ?, updated_at = ? WHERE build_id = ?",
                (status, now, job["build_id"]),
            )
        return status

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_build(self, build_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT b.*, j.job_id, j.status AS job_status, j.attempts, j.last_error
                FROM artifact_builds b JOIN analysis_jobs j USING(build_id)
                WHERE b.build_id = ?
                """,
                (build_id,),
            ).fetchone()
        return _decode_build(row)

    def list_builds(self, project: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT b.*, j.job_id, j.status AS job_status, j.attempts, j.last_error
                FROM artifact_builds b JOIN analysis_jobs j USING(build_id)
                WHERE b.project = ? ORDER BY b.created_at DESC LIMIT ?
                """,
                (project, min(max(limit, 1), 100)),
            ).fetchall()
        return [decoded for row in rows if (decoded := _decode_build(row)) is not None]

    def latest_completed_build(self, project: str, exclude_build_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            current = connection.execute(
                "SELECT created_at FROM artifact_builds WHERE build_id = ?",
                (exclude_build_id,),
            ).fetchone()
            if current is None:
                return None
            row = connection.execute(
                """
                SELECT * FROM artifact_builds
                WHERE project = ? AND status = 'completed' AND created_at < ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (project, current["created_at"]),
            ).fetchone()
        return _decode_build(row)

    def list_diffs(self, build_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT path, status, difference_ratio, baseline_sha256, current_sha256,
                       width, height
                FROM snapshot_diffs WHERE build_id = ?
                ORDER BY status DESC, path
                """,
                (build_id,),
            ).fetchall()
        return [dict(row) for row in rows]
