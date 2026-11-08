from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from traceharbor.artifact_repository import ArtifactRepository
from traceharbor.artifact_service import ArtifactService, ArtifactWorkerPool
from traceharbor.artifact_store import ArtifactTooLargeError, LocalArtifactStore
from traceharbor.models import ValidationError
from traceharbor.snapshots import AnalysisResult, SnapshotAnalyzer


def png(color: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 8), color).save(output, format="PNG")
    return output.getvalue()


def bundle(files: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return output.getvalue()


class ArtifactPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.repository = ArtifactRepository(root / "test.db")
        self.object_store = LocalArtifactStore(root / "artifacts")
        self.service = ArtifactService(
            self.repository,
            self.object_store,
            "test-key",
            max_artifact_bytes=1_000_000,
            max_attempts=3,
        )
        self.analyzer = SnapshotAnalyzer(
            self.repository,
            self.object_store,
            max_snapshots=100,
            max_uncompressed_bytes=1_000_000,
        )
        self.worker = ArtifactWorkerPool(
            self.repository,
            self.analyzer,
            worker_count=1,
            retry_base_seconds=0,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def submit(self, payload: bytes, key: str):
        return self.service.submit_snapshots(
            project="demo",
            idempotency_key=key,
            baseline_build_id=None,
            content_length=len(payload),
            stream=BytesIO(payload),
            provided_api_key="test-key",
        )

    def test_idempotency_key_replays_original_submission(self) -> None:
        payload = bundle({"home.png": png("green")})
        first = self.submit(payload, "commit-123456")
        replay = self.submit(payload, "commit-123456")
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.build_id, first.build_id)
        self.assertEqual(replay.job_id, first.job_id)

    def test_object_store_streams_in_bounded_chunks(self) -> None:
        payload = b"x" * (LocalArtifactStore.chunk_size * 2 + 17)

        class TrackingStream(BytesIO):
            largest_read = 0

            def read(self, size: int = -1) -> bytes:
                self.largest_read = max(self.largest_read, size)
                return super().read(size)

        stream = TrackingStream(payload)
        stored = self.object_store.put_stream(stream, len(payload), len(payload))
        self.assertEqual(stored.size_bytes, len(payload))
        self.assertLessEqual(stream.largest_read, LocalArtifactStore.chunk_size)

    def test_object_store_rejects_declared_oversize_before_reading(self) -> None:
        class UnreadableStream(BytesIO):
            def read(self, size: int = -1) -> bytes:
                raise AssertionError("oversized body should not be read")

        with self.assertRaises(ArtifactTooLargeError):
            self.object_store.put_stream(UnreadableStream(b"x"), 101, 100)

    def test_explicit_baseline_must_already_be_completed(self) -> None:
        baseline = self.submit(bundle({"home.png": png("green")}), "pending-12345678")
        payload = bundle({"home.png": png("blue")})
        with self.assertRaises(ValidationError):
            self.service.submit_snapshots(
                project="demo",
                idempotency_key="followup-123456",
                baseline_build_id=baseline.build_id,
                content_length=len(payload),
                stream=BytesIO(payload),
                provided_api_key="test-key",
            )

    def test_expired_worker_cannot_commit_after_job_is_reclaimed(self) -> None:
        submitted = self.submit(bundle({"home.png": png("green")}), "lease-123456789")
        first = self.repository.claim_job("worker-one", lease_seconds=0)
        second = self.repository.claim_job("worker-two", lease_seconds=60)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertFalse(
            self.repository.complete_job(
                submitted.job_id,
                "worker-one",
                {"snapshot_count": 0, "counts": {}, "changed": 0},
                [],
            )
        )
        self.assertTrue(
            self.repository.complete_job(
                submitted.job_id,
                "worker-two",
                {"snapshot_count": 0, "counts": {}, "changed": 0},
                [],
            )
        )

    def test_compares_changed_added_and_removed_snapshots(self) -> None:
        baseline = self.submit(
            bundle({"home.png": png("green"), "cart.png": png("blue")}),
            "baseline-123456",
        )
        self.assertTrue(self.worker.run_once())
        self.assertEqual(self.repository.get_job(baseline.job_id)["status"], "completed")

        changed = self.submit(
            bundle({"home.png": png("yellow"), "profile.png": png("purple")}),
            "changed-1234567",
        )
        self.assertTrue(self.worker.run_once())
        build = self.repository.get_build(changed.build_id)
        self.assertEqual(build["status"], "completed")
        self.assertEqual(build["summary"]["changed"], 3)
        diffs = self.repository.list_diffs(changed.build_id)
        statuses = {item["path"]: item["status"] for item in diffs}
        self.assertEqual(
            statuses,
            {"cart.png": "removed", "home.png": "changed", "profile.png": "added"},
        )
        home = next(item for item in diffs if item["path"] == "home.png")
        self.assertGreater(home["difference_ratio"], 0)

    def test_rejects_unsafe_archive_path_without_retrying(self) -> None:
        submitted = self.submit(bundle({"../escape.png": png("red")}), "unsafe-12345678")
        self.assertTrue(self.worker.run_once())
        job = self.repository.get_job(submitted.job_id)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["attempts"], 1)

    def test_transient_worker_failure_is_retried(self) -> None:
        submitted = self.submit(bundle({"home.png": png("green")}), "retry-123456789")

        class FlakyAnalyzer:
            calls = 0

            def analyze(self, _build_id: str) -> AnalysisResult:
                self.calls += 1
                if self.calls == 1:
                    raise OSError("temporary object-store failure")
                return AnalysisResult(summary={"snapshot_count": 0, "counts": {}, "changed": 0}, diffs=[])

        worker = ArtifactWorkerPool(
            self.repository,
            FlakyAnalyzer(),  # type: ignore[arg-type]
            worker_count=1,
            retry_base_seconds=0,
        )
        self.assertTrue(worker.run_once())
        self.assertEqual(self.repository.get_job(submitted.job_id)["status"], "queued")
        self.assertTrue(worker.run_once())
        job = self.repository.get_job(submitted.job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["attempts"], 2)


if __name__ == "__main__":
    unittest.main()
