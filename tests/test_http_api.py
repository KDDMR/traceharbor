from __future__ import annotations

import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from traceharbor.config import Settings
from traceharbor.http_api import create_http_server
from traceharbor.service import TelemetryService
from traceharbor.storage import EventStore


class HTTPAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        settings = Settings(port=0, database_path=Path(self.temp_dir.name) / "test.db", api_key="test-key")
        store = EventStore(settings.database_path)
        self.server = create_http_server(TelemetryService(store, settings.api_key), settings)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def request(self, path: str, payload: dict | None = None, api_key: str | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        request = Request(self.base_url + path, data=data, headers=headers)
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read())

    def test_health_endpoint(self) -> None:
        status, body = self.request("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_ingest_and_query_round_trip(self) -> None:
        status, accepted = self.request(
            "/api/events",
            {
                "type": "error",
                "project": "demo",
                "exception": {"type": "RuntimeError", "value": "boom", "frames": []},
            },
            "test-key",
        )
        self.assertEqual(status, 202)
        self.assertEqual(accepted["accepted"], 1)
        _, issues = self.request("/api/issues?project=demo")
        self.assertEqual(issues["items"][0]["title"], "RuntimeError: boom")

    def test_rejects_missing_api_key(self) -> None:
        with self.assertRaises(HTTPError) as raised:
            self.request("/api/events", {"type": "message", "project": "demo", "message": "hi"})
        self.assertEqual(raised.exception.code, 401)

    def test_serves_dashboard(self) -> None:
        with urlopen(self.base_url + "/", timeout=2) as response:
            html = response.read().decode()
        self.assertIn("Issues, without the noise", html)


if __name__ == "__main__":
    unittest.main()

