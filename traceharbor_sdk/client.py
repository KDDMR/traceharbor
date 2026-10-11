"""Small telemetry client with capture helpers, batching and bounded retries."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
import queue
import random
from threading import Event, Lock, Thread
import time
import traceback
from types import TracebackType
from typing import Any, Callable, Protocol
from uuid import uuid4

from .transport import HttpTransport


class Transport(Protocol):
    def send(self, events: list[dict[str, Any]]) -> None: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Client:
    """Capture telemetry without blocking application code on normal delivery."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        project: str,
        *,
        release: str = "unknown",
        environment: str = "development",
        batch_size: int = 10,
        flush_interval: float = 1.0,
        max_retries: int = 3,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        start_worker: bool = True,
    ) -> None:
        if batch_size <= 0 or flush_interval <= 0 or max_retries < 0:
            raise ValueError("invalid delivery configuration")
        self.project = project
        self.release = release
        self.environment = environment
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_retries = max_retries
        self.transport = transport or HttpTransport(endpoint, api_key)
        self._sleep = sleep
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1_000)
        self._stop = Event()
        self._wake = Event()
        self._flush_lock = Lock()
        self.dropped_events = 0
        self._worker: Thread | None = None
        if start_worker:
            self._worker = Thread(target=self._run, name="traceharbor-delivery", daemon=True)
            self._worker.start()

    def capture_message(
        self,
        message: str,
        *,
        level: str = "info",
        tags: dict[str, str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        return self._enqueue(
            self._base_event("message", level, tags, context) | {"message": message}
        )

    def capture_exception(
        self,
        error: BaseException,
        *,
        tags: dict[str, str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        frames = [
            {"filename": frame.filename, "function": frame.name, "lineno": frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__)
        ]
        return self._enqueue(
            self._base_event("error", "error", tags, context)
            | {
                "message": str(error),
                "exception": {
                    "type": type(error).__name__,
                    "value": str(error),
                    "frames": frames,
                },
            }
        )

    def transaction(
        self,
        name: str,
        *,
        tags: dict[str, str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> "Transaction":
        return Transaction(self, name, tags=tags, context=context)

    def flush(self) -> None:
        """Synchronously deliver everything currently queued."""
        with self._flush_lock:
            while True:
                batch = self._drain(self.batch_size)
                if not batch:
                    return
                self._deliver(batch)

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._worker is not None:
            self._worker.join(timeout=max(2.0, self.flush_interval * 2))
        self.flush()

    def _base_event(
        self,
        event_type: str,
        level: str,
        tags: dict[str, str] | None,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "event_id": str(uuid4()),
            "timestamp": _now(),
            "type": event_type,
            "project": self.project,
            "level": level,
            "release": self.release,
            "environment": self.environment,
            "tags": tags or {},
            "context": context or {},
        }

    def _enqueue(self, event: dict[str, Any]) -> str:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped_events += 1
        if self._queue.qsize() >= self.batch_size:
            self._wake.set()
        return event["event_id"]

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self.flush_interval)
            self._wake.clear()
            try:
                self.flush()
            except Exception:
                # Telemetry must never crash the host application. Delivery is best effort.
                continue
        try:
            self.flush()
        except Exception:
            pass

    def _drain(self, limit: int) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for _ in range(limit):
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    def _deliver(self, events: list[dict[str, Any]]) -> None:
        for attempt in range(self.max_retries + 1):
            try:
                self.transport.send(events)
                return
            except Exception:
                if attempt >= self.max_retries:
                    self.dropped_events += len(events)
                    return
                delay = min(2**attempt * 0.1, 2.0) + random.uniform(0.0, 0.05)
                self._sleep(delay)


class Transaction(AbstractContextManager["Transaction"]):
    def __init__(
        self,
        client: Client,
        name: str,
        *,
        tags: dict[str, str] | None,
        context: dict[str, Any] | None,
    ) -> None:
        self.client = client
        self.name = name
        self.tags = tags
        self.context = context
        self.started_at = 0.0

    def __enter__(self) -> "Transaction":
        self.started_at = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        duration_ms = (time.perf_counter() - self.started_at) * 1_000
        status = "error" if exc is not None else "ok"
        event = self.client._base_event("transaction", "info", self.tags, self.context)
        event.update(
            {
                "transaction": self.name,
                "duration_ms": duration_ms,
                "tags": event["tags"] | {"status": status},
            }
        )
        self.client._enqueue(event)
        if exc is not None:
            self.client.capture_exception(
                exc,
                tags=(self.tags or {}) | {"transaction": self.name},
                context=self.context,
            )
        return False
