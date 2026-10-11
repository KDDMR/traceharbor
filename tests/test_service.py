from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from traceharbor.models import ValidationError
from traceharbor.service import TelemetryService, UnauthorizedError
from traceharbor.storage import EventStore


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.temp_dir.name) / "test.db")
        self.service = TelemetryService(self.store, "test-key", rate_limit_per_minute=100)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_rejects_invalid_api_key(self) -> None:
        with self.assertRaises(UnauthorizedError):
            self.service.ingest([], "wrong")

    def test_reports_duplicate_events(self) -> None:
        payload = {"type": "message", "project": "demo", "message": "deployed"}
        first = self.service.ingest([payload], "test-key")
        payload["event_id"] = first.event_ids[0]
        second = self.service.ingest([payload], "test-key")
        self.assertEqual((second.accepted, second.duplicates), (0, 1))

    def test_validates_full_envelope_before_writing(self) -> None:
        valid = {"type": "message", "project": "demo", "message": "hello"}
        invalid = {"type": "error", "project": "demo"}
        with self.assertRaises(ValidationError):
            self.service.ingest([valid, invalid], "test-key")
        self.assertEqual(self.store.metrics("demo")["event_count"], 0)


if __name__ == "__main__":
    unittest.main()

