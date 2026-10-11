from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from traceharbor.processing import prepare_event
from traceharbor.storage import EventStore


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = EventStore(Path(self.temp_dir.name) / "test.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _error(self, value: str = "bad input") -> dict:
        return prepare_event(
            {
                "type": "error",
                "project": "demo",
                "exception": {
                    "type": "ValueError",
                    "value": value,
                    "frames": [{"filename": "app.py", "function": "checkout", "lineno": 4}],
                },
            }
        )

    def test_groups_repeated_events(self) -> None:
        self.store.add_event(self._error("order 10 failed"))
        self.store.add_event(self._error("order 20 failed"))
        issues = self.store.list_issues("demo")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["event_count"], 2)

    def test_duplicate_event_id_is_idempotent(self) -> None:
        event = self._error()
        self.assertTrue(self.store.add_event(event))
        self.assertFalse(self.store.add_event(event))
        self.assertEqual(self.store.list_issues("demo")[0]["event_count"], 1)

    def test_returns_issue_with_recent_events(self) -> None:
        event = self._error()
        self.store.add_event(event)
        issue = self.store.get_issue("demo", event["fingerprint"])
        self.assertIsNotNone(issue)
        self.assertEqual(issue["events"][0]["event_id"], event["event_id"])

    def test_metrics_include_transaction_duration(self) -> None:
        event = prepare_event(
            {"type": "transaction", "project": "demo", "transaction": "GET /", "duration_ms": 25}
        )
        self.store.add_event(event)
        self.assertEqual(
            self.store.metrics("demo"),
            {"event_count": 1, "error_count": 0, "transaction_count": 1, "issue_count": 0, "avg_duration_ms": 25.0},
        )


if __name__ == "__main__":
    unittest.main()

