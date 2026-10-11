from __future__ import annotations

import unittest
from uuid import uuid4

from traceharbor.models import ValidationError, validate_event


class EventValidationTests(unittest.TestCase):
    def test_normalizes_valid_error_event(self) -> None:
        event = validate_event(
            {
                "event_id": str(uuid4()),
                "type": "error",
                "project": "checkout-api",
                "exception": {"type": "ValueError", "value": "bad input", "frames": []},
                "tags": {"attempt": 2},
            }
        )
        self.assertEqual(event["level"], "error")
        self.assertEqual(event["tags"], {"attempt": "2"})
        self.assertTrue(event["timestamp"].endswith("+00:00"))

    def test_generates_event_id_when_missing(self) -> None:
        event = validate_event({"type": "message", "project": "demo", "message": "hello"})
        self.assertEqual(len(event["event_id"]), 36)

    def test_rejects_unknown_type(self) -> None:
        with self.assertRaisesRegex(ValidationError, "type must be"):
            validate_event({"type": "metric", "project": "demo"})

    def test_requires_exception_for_error_event(self) -> None:
        with self.assertRaisesRegex(ValidationError, "require an exception"):
            validate_event({"type": "error", "project": "demo"})

    def test_requires_duration_for_transaction(self) -> None:
        with self.assertRaisesRegex(ValidationError, "duration_ms"):
            validate_event({"type": "transaction", "project": "demo", "transaction": "GET /"})

    def test_rejects_invalid_project_slug(self) -> None:
        with self.assertRaisesRegex(ValidationError, "project"):
            validate_event({"type": "message", "project": "x", "message": "hello"})


if __name__ == "__main__":
    unittest.main()

