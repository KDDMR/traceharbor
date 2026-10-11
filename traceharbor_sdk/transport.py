"""HTTP transport kept separate to make delivery testable and replaceable."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TransportError(RuntimeError):
    pass


class HttpTransport:
    def __init__(self, endpoint: str, api_key: str, timeout: float = 5.0) -> None:
        self.endpoint = endpoint.rstrip("/") + "/api/envelope"
        self.api_key = api_key
        self.timeout = timeout

    def send(self, events: list[dict[str, Any]]) -> None:
        body = json.dumps({"events": events}, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self.api_key,
                "User-Agent": "traceharbor-python/0.1.0",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                if response.status >= 300:
                    raise TransportError(f"ingest returned HTTP {response.status}")
        except HTTPError as exc:
            raise TransportError(f"ingest returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise TransportError(f"ingest unavailable: {exc.reason}") from exc
