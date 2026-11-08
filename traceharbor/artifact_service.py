"""Artifact submission use case and durable worker-pool execution."""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from threading import Event, Lock, Thread
from typing import BinaryIO
from uuid import uuid4

from .artifact_repository import ArtifactRepository
from .artifact_store import LocalArtifactStore
from .models import PROJECT_PATTERN, ValidationError
from .service import UnauthorizedError
from .snapshots import PermanentAnalysisError, SnapshotAnalyzer

LOGGER = logging.getLogger("traceharbor.artifacts")


@dataclass(frozen=True, slots=True)
class ArtifactSubmission:
    build_id: str
    job_id: str
    status: str
    replayed: bool
    sha256: str
    size_bytes: int


class ArtifactService:
    def __init__(
        self,
        repository: ArtifactRepository,
        object_store: LocalArtifactStore,
        api_key: str,
        *,
        max_artifact_bytes: int,
        max_attempts: int,
    ) -> None:
        self.repository = repository
        self.object_store = object_store
        self.api_key = api_key
        self.max_artifact_bytes = max_artifact_bytes
        self.max_attempts = max_attempts
        self._submission_lock = Lock()

    def submit_snapshots(
        self,
        *,
        project: str,
        idempotency_key: str,
        baseline_build_id: str | None,
        content_length: int,
        stream: BinaryIO,
        provided_api_key: str | None,
    ) -> ArtifactSubmission:
        self._authorize(provided_api_key)
        if not PROJECT_PATTERN.fullmatch(project):
            raise ValidationError("project must be 2-64 letters, numbers, underscores or dashes")
        if not 8 <= len(idempotency_key) <= 200:
            raise ValidationError("X-Idempotency-Key must contain 8-200 characters")
        if baseline_build_id is not None:
            baseline = self.repository.get_build(baseline_build_id)
            if baseline is None or baseline["project"] != project:
                raise ValidationError("X-Baseline-Build-Id must reference this project")
            if baseline["status"] != "completed":
                raise ValidationError("X-Baseline-Build-Id must reference a completed build")

        # The lock closes the local race between checking the key and storing the
        # object. The database uniqueness constraint remains the final guard.
        with self._submission_lock:
            existing = self.repository.find_by_idempotency(project, idempotency_key)
            if existing is not None:
                self._discard(stream, content_length)
                return self._submission(existing, replayed=True)

            stored = self.object_store.put_stream(stream, content_length, self.max_artifact_bytes)
            build, replayed = self.repository.create_submission(
                build_id=str(uuid4()),
                job_id=str(uuid4()),
                project=project,
                object_key=stored.object_key,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                idempotency_key=idempotency_key,
                baseline_build_id=baseline_build_id,
                max_attempts=self.max_attempts,
            )
            return self._submission(build, replayed=replayed)

    @staticmethod
    def _discard(stream: BinaryIO, content_length: int) -> None:
        remaining = content_length
        while remaining:
            chunk = stream.read(min(LocalArtifactStore.chunk_size, remaining))
            if not chunk:
                raise ValidationError("artifact body ended before Content-Length")
            remaining -= len(chunk)

    def _authorize(self, provided_api_key: str | None) -> None:
        if not provided_api_key or not hmac.compare_digest(provided_api_key, self.api_key):
            raise UnauthorizedError("invalid API key")

    @staticmethod
    def _submission(build: dict, replayed: bool) -> ArtifactSubmission:
        return ArtifactSubmission(
            build_id=build["build_id"],
            job_id=build["job_id"],
            status=build["job_status"],
            replayed=replayed,
            sha256=build["sha256"],
            size_bytes=build["size_bytes"],
        )


class ArtifactWorkerPool:
    """Lease durable jobs to a bounded set of background workers."""

    def __init__(
        self,
        repository: ArtifactRepository,
        analyzer: SnapshotAnalyzer,
        *,
        worker_count: int = 2,
        lease_seconds: int = 60,
        retry_base_seconds: float = 1.0,
        poll_interval: float = 0.25,
    ) -> None:
        self.repository = repository
        self.analyzer = analyzer
        self.worker_count = max(worker_count, 1)
        self.lease_seconds = lease_seconds
        self.retry_base_seconds = retry_base_seconds
        self.poll_interval = poll_interval
        self._stop = Event()
        self._threads: list[Thread] = []

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for number in range(self.worker_count):
            worker_id = f"worker-{number + 1}-{uuid4().hex[:8]}"
            thread = Thread(target=self._run, args=(worker_id,), daemon=True, name=worker_id)
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    def _run(self, worker_id: str) -> None:
        while not self._stop.is_set():
            if not self.run_once(worker_id):
                self._stop.wait(self.poll_interval)

    def run_once(self, worker_id: str = "test-worker") -> bool:
        job = self.repository.claim_job(worker_id, self.lease_seconds)
        if job is None:
            return False
        try:
            result = self.analyzer.analyze(job["build_id"])
            self.repository.complete_job(job["job_id"], worker_id, result.summary, result.diffs)
            LOGGER.info("artifact_analysis_completed build_id=%s", job["build_id"])
        except PermanentAnalysisError as exc:
            self.repository.fail_job(
                job["job_id"], worker_id, str(exc), retryable=False, retry_delay=0
            )
            LOGGER.warning("artifact_analysis_rejected build_id=%s error=%s", job["build_id"], exc)
        except Exception as exc:
            delay = self.retry_base_seconds * (2 ** max(job["attempts"] - 1, 0))
            state = self.repository.fail_job(
                job["job_id"], worker_id, str(exc), retryable=True, retry_delay=delay
            )
            LOGGER.exception(
                "artifact_analysis_failed build_id=%s next_state=%s", job["build_id"], state
            )
        return True
