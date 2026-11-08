"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8080
    database_path: Path = Path("traceharbor.db")
    api_key: str = "dev-key"
    max_payload_bytes: int = 256_000
    rate_limit_per_minute: int = 120
    artifact_directory: Path = Path("traceharbor-artifacts")
    max_artifact_bytes: int = 50_000_000
    max_uncompressed_artifact_bytes: int = 500_000_000
    max_snapshots_per_artifact: int = 10_000
    artifact_worker_count: int = 2
    artifact_job_max_attempts: int = 3
    artifact_job_lease_seconds: int = 60

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            host=os.getenv("TRACEHARBOR_HOST", "127.0.0.1"),
            port=int(os.getenv("TRACEHARBOR_PORT", "8080")),
            database_path=Path(os.getenv("TRACEHARBOR_DB", "traceharbor.db")),
            api_key=os.getenv("TRACEHARBOR_API_KEY", "dev-key"),
            max_payload_bytes=int(os.getenv("TRACEHARBOR_MAX_PAYLOAD", "256000")),
            rate_limit_per_minute=int(os.getenv("TRACEHARBOR_RATE_LIMIT", "120")),
            artifact_directory=Path(
                os.getenv("TRACEHARBOR_ARTIFACT_DIR", "traceharbor-artifacts")
            ),
            max_artifact_bytes=int(os.getenv("TRACEHARBOR_MAX_ARTIFACT", "50000000")),
            max_uncompressed_artifact_bytes=int(
                os.getenv("TRACEHARBOR_MAX_UNCOMPRESSED_ARTIFACT", "500000000")
            ),
            max_snapshots_per_artifact=int(
                os.getenv("TRACEHARBOR_MAX_SNAPSHOTS", "10000")
            ),
            artifact_worker_count=int(os.getenv("TRACEHARBOR_WORKERS", "2")),
            artifact_job_max_attempts=int(os.getenv("TRACEHARBOR_JOB_ATTEMPTS", "3")),
            artifact_job_lease_seconds=int(os.getenv("TRACEHARBOR_JOB_LEASE_SECONDS", "60")),
        )
