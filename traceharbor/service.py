"""Application service coordinating validation, grouping and persistence."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
from typing import Any

from .processing import prepare_event
from .rate_limit import TokenBucketRateLimiter
from .storage import EventStore


class UnauthorizedError(PermissionError):
    pass


class RateLimitError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IngestResult:
    accepted: int
    duplicates: int
    event_ids: list[str]


class TelemetryService:
    def __init__(self, store: EventStore, api_key: str, rate_limit_per_minute: int = 120) -> None:
        self.store = store
        self.api_key = api_key
        self.rate_limiter = TokenBucketRateLimiter(rate_limit_per_minute)

    def _authorize(self, provided_api_key: str | None) -> None:
        if not provided_api_key or not hmac.compare_digest(provided_api_key, self.api_key):
            raise UnauthorizedError("invalid API key")

    def ingest(self, payloads: list[Any], provided_api_key: str | None) -> IngestResult:
        self._authorize(provided_api_key)
        if not payloads:
            return IngestResult(accepted=0, duplicates=0, event_ids=[])
        if len(payloads) > 100:
            raise ValueError("an envelope may contain at most 100 events")
        if not self.rate_limiter.allow(provided_api_key or "anonymous", cost=len(payloads)):
            raise RateLimitError("rate limit exceeded")

        prepared = [prepare_event(payload) for payload in payloads]
        accepted = 0
        duplicates = 0
        event_ids: list[str] = []
        for event in prepared:
            if self.store.add_event(event):
                accepted += 1
            else:
                duplicates += 1
            event_ids.append(event["event_id"])
        return IngestResult(accepted=accepted, duplicates=duplicates, event_ids=event_ids)
