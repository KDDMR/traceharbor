"""HTTP adapter and static dashboard for TraceHarbor."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .config import Settings
from .models import ValidationError
from .service import RateLimitError, TelemetryService, UnauthorizedError


LOGGER = logging.getLogger("traceharbor.http")
STATIC_ROOT = Path(__file__).with_name("static")
ISSUE_PATH = re.compile(r"^/api/issues/([a-f0-9]{24})$")


class TraceHarborHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], service: TelemetryService, settings: Settings) -> None:
        super().__init__(address, TraceHarborHandler)
        self.service = service
        self.settings = settings


class TraceHarborHandler(BaseHTTPRequestHandler):
    server: TraceHarborHTTPServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler interface
        request_id = str(uuid4())
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/health":
                self._json(HTTPStatus.OK, {"status": "ok", "service": "traceharbor"}, request_id)
            elif parsed.path == "/api/issues":
                query = parse_qs(parsed.query)
                project = query.get("project", ["demo-store"])[0]
                limit = int(query.get("limit", ["50"])[0])
                self._json(
                    HTTPStatus.OK,
                    {"items": self.server.service.store.list_issues(project, limit)},
                    request_id,
                )
            elif parsed.path == "/api/metrics":
                project = parse_qs(parsed.query).get("project", ["demo-store"])[0]
                self._json(HTTPStatus.OK, self.server.service.store.metrics(project), request_id)
            elif match := ISSUE_PATH.match(parsed.path):
                project = parse_qs(parsed.query).get("project", ["demo-store"])[0]
                issue = self.server.service.store.get_issue(project, match.group(1))
                if issue is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "issue not found"}, request_id)
                else:
                    self._json(HTTPStatus.OK, issue, request_id)
            elif parsed.path in {"/", "/index.html"}:
                self._static("index.html", "text/html; charset=utf-8", request_id)
            elif parsed.path == "/app.js":
                self._static("app.js", "text/javascript; charset=utf-8", request_id)
            elif parsed.path == "/styles.css":
                self._static("styles.css", "text/css; charset=utf-8", request_id)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "route not found"}, request_id)
        except (ValueError, TypeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)}, request_id)
        except Exception:
            LOGGER.exception("request_failed", extra={"request_id": request_id})
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"}, request_id)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler interface
        request_id = str(uuid4())
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/events", "/api/envelope"}:
            self._json(HTTPStatus.NOT_FOUND, {"error": "route not found"}, request_id)
            return

        try:
            payload = self._read_json()
            if parsed.path == "/api/events":
                events = [payload]
            else:
                if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
                    raise ValidationError("envelope must contain an events array")
                events = payload["events"]
            result = self.server.service.ingest(events, self.headers.get("X-API-Key"))
            self._json(
                HTTPStatus.ACCEPTED,
                {
                    "accepted": result.accepted,
                    "duplicates": result.duplicates,
                    "event_ids": result.event_ids,
                },
                request_id,
            )
        except UnauthorizedError as exc:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": str(exc)}, request_id)
        except RateLimitError as exc:
            self._json(
                HTTPStatus.TOO_MANY_REQUESTS,
                {"error": str(exc)},
                request_id,
                extra_headers={"Retry-After": "60"},
            )
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)}, request_id)
        except Exception:
            LOGGER.exception("ingest_failed", extra={"request_id": request_id})
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"}, request_id)

    def _read_json(self) -> Any:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValidationError("Content-Length is required")
        length = int(raw_length)
        if length <= 0 or length > self.server.settings.max_payload_bytes:
            raise ValidationError("request body has an invalid size")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _json(
        self,
        status: HTTPStatus,
        body: Any,
        request_id: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        data = json.dumps(body, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Request-Id", request_id)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _static(self, filename: str, content_type: str, request_id: str) -> None:
        data = (STATIC_ROOT / filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Request-Id", request_id)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format_string: str, *args: object) -> None:
        LOGGER.info("http_request method=%s path=%s status=%s", self.command, self.path, args[1])


def create_http_server(service: TelemetryService, settings: Settings) -> TraceHarborHTTPServer:
    return TraceHarborHTTPServer((settings.host, settings.port), service, settings)
