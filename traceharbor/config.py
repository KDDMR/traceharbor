"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8080
    database_path: Path = Path("traceharbor.db")
    api_key: str = "dev-key"
    max_payload_bytes: int = 256_000
    rate_limit_per_minute: int = 120

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("TRACEHARBOR_HOST", "127.0.0.1"),
            port=int(os.getenv("TRACEHARBOR_PORT", "8080")),
            database_path=Path(os.getenv("TRACEHARBOR_DB", "traceharbor.db")),
            api_key=os.getenv("TRACEHARBOR_API_KEY", "dev-key"),
            max_payload_bytes=int(os.getenv("TRACEHARBOR_MAX_PAYLOAD", "256000")),
            rate_limit_per_minute=int(os.getenv("TRACEHARBOR_RATE_LIMIT", "120")),
        )
