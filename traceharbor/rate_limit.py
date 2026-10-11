"""Thread-safe token bucket rate limiting."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
import time


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketRateLimiter:
    def __init__(self, capacity: int, per_seconds: float = 60.0) -> None:
        if capacity <= 0 or per_seconds <= 0:
            raise ValueError("capacity and per_seconds must be positive")
        self.capacity = float(capacity)
        self.refill_per_second = capacity / per_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._lock = Lock()

    def allow(self, key: str, cost: float = 1.0, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self.capacity, updated_at=current)
                self._buckets[key] = bucket
            elapsed = max(0.0, current - bucket.updated_at)
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_per_second)
            bucket.updated_at = current
            if bucket.tokens < cost:
                return False
            bucket.tokens -= cost
            return True
