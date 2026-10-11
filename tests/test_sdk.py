from __future__ import annotations

import unittest

from traceharbor_sdk import Client


class RecordingTransport:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.attempts = 0
        self.batches: list[list[dict]] = []

    def send(self, events: list[dict]) -> None:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise RuntimeError("temporary failure")
        self.batches.append(events)


class SDKTests(unittest.TestCase):
    def client(self, transport: RecordingTransport, **kwargs: object) -> Client:
        return Client(
            "http://unused",
            "key",
            "demo",
            transport=transport,
            start_worker=False,
            sleep=lambda _delay: None,
            **kwargs,
        )

    def test_batches_queued_events(self) -> None:
        transport = RecordingTransport()
        client = self.client(transport, batch_size=2)
        client.capture_message("one")
        client.capture_message("two")
        client.capture_message("three")
        client.flush()
        self.assertEqual([len(batch) for batch in transport.batches], [2, 1])

    def test_retries_transient_delivery_failures(self) -> None:
        transport = RecordingTransport(failures=2)
        client = self.client(transport, max_retries=2)
        client.capture_message("retry me")
        client.flush()
        self.assertEqual(transport.attempts, 3)
        self.assertEqual(client.dropped_events, 0)

    def test_counts_event_after_retry_budget_is_exhausted(self) -> None:
        transport = RecordingTransport(failures=5)
        client = self.client(transport, max_retries=1)
        client.capture_message("drop me")
        client.flush()
        self.assertEqual(client.dropped_events, 1)

    def test_transaction_records_duration_and_status(self) -> None:
        transport = RecordingTransport()
        client = self.client(transport)
        with client.transaction("checkout"):
            pass
        client.flush()
        event = transport.batches[0][0]
        self.assertEqual(event["type"], "transaction")
        self.assertEqual(event["tags"]["status"], "ok")
        self.assertGreaterEqual(event["duration_ms"], 0)

    def test_transaction_does_not_swallow_exception(self) -> None:
        transport = RecordingTransport()
        client = self.client(transport)
        with self.assertRaises(ValueError):
            with client.transaction("checkout"):
                raise ValueError("broken")
        client.flush()
        event_types = [event["type"] for batch in transport.batches for event in batch]
        self.assertEqual(event_types, ["transaction", "error"])


if __name__ == "__main__":
    unittest.main()

