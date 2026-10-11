from __future__ import annotations

import unittest

from traceharbor.processing import prepare_event, redact


class ProcessingTests(unittest.TestCase):
    def test_redacts_sensitive_values_recursively(self) -> None:
        value = {
            "authorization": "Bearer secret",
            "user": {"email": "kadir@example.com", "token": "abc"},
        }
        self.assertEqual(
            redact(value),
            {
                "authorization": "[Filtered]",
                "user": {"email": "[email]", "token": "[Filtered]"},
            },
        )

    def test_groups_errors_by_exception_and_top_frame(self) -> None:
        base = {
            "type": "error",
            "project": "demo",
            "exception": {
                "type": "ValueError",
                "value": "order 123 failed",
                "frames": [{"filename": "checkout.py", "function": "pay", "lineno": 10}],
            },
        }
        first = prepare_event(base)
        second = prepare_event(
            base
            | {
                "exception": base["exception"]
                | {"value": "order 999 failed", "frames": [{"filename": "checkout.py", "function": "pay", "lineno": 42}]}
            }
        )
        self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_separates_different_call_sites(self) -> None:
        first = prepare_event(
            {
                "type": "error",
                "project": "demo",
                "exception": {"type": "ValueError", "value": "bad", "frames": [{"filename": "a.py", "function": "one"}]},
            }
        )
        second = prepare_event(
            {
                "type": "error",
                "project": "demo",
                "exception": {"type": "ValueError", "value": "bad", "frames": [{"filename": "b.py", "function": "two"}]},
            }
        )
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])

    def test_normalizes_dynamic_message_values(self) -> None:
        first = prepare_event({"type": "message", "project": "demo", "message": "Order 1234 failed"})
        second = prepare_event({"type": "message", "project": "demo", "message": "Order 9999 failed"})
        self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_transactions_are_not_grouped_as_issues(self) -> None:
        event = prepare_event(
            {"type": "transaction", "project": "demo", "transaction": "GET /cart", "duration_ms": 12.3}
        )
        self.assertIsNone(event["fingerprint"])


if __name__ == "__main__":
    unittest.main()

