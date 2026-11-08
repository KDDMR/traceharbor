"""HTTP adapter and static dashboard for TraceHarbor."""

from __future__ import annotations

import json
import logging
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, BinaryIO, cast
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .artifact_repository import ArtifactRepository
from .artifact_service import ArtifactService
from .artifact_store import ArtifactStorageError, ArtifactTooLargeError, LocalArtifactStore
from .config import Settings
from .models import ValidationError
from .service import RateLimitError, TelemetryService, UnauthorizedError

LOGGER = logging.getLogger("traceharbor.http")
STATIC_ROOT = Path(__file__).with_name("static")
ISSUE_PATH = re.compile(r"^/api/issues/([a-f0-9]{24})$")
JOB_PATH = re.compile(r"^/api/jobs/([0-9a-f-]{36})$")
BUILD_PATH = re.compile(r"^/api/builds/([0-9a-f-]{36})$")
BUILD_DIFF_PATH = re.compile(r"^/api/builds/([0-9a-f-]{36})/diffs$")


class TraceHarborHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        service: TelemetryService,
        artifact_service: ArtifactService,
        artifact_repository: ArtifactRepository,
        settings: Settings,
    ) -> None:
        super().__init__(address, TraceHarborHandler)
        self.service = service
        self.artifact_service = artifact_service
        self.artifact_repository = artifact_repository
        self.settings = settings


class TraceHarborHandler(BaseHTTPRequestHandler):
    server: TraceHarborHTTPServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
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
            elif parsed.path == "/api/builds":
                query = parse_qs(parsed.query)
                project = query.get("project", ["demo-store"])[0]
                limit = int(query.get("limit", ["30"])[0])
                self._json(
                    HTTPStatus.OK,
                    {"items": self.server.artifact_repository.list_builds(project, limit)},
                    request_id,
                )
            elif match := BUILD_DIFF_PATH.match(parsed.path):
                build = self.server.artifact_repository.get_build(match.group(1))
                if build is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "build not found"}, request_id)
                else:
                    self._json(
                        HTTPStatus.OK,
                        {"items": self.server.artifact_repository.list_diffs(match.group(1))},
                        request_id,
                    )
            elif match := BUILD_PATH.match(parsed.path):
                build = self.server.artifact_repository.get_build(match.group(1))
                if build is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "build not found"}, request_id)
                else:
                    build["diffs"] = self.server.artifact_repository.list_diffs(match.group(1))
                    self._json(HTTPStatus.OK, build, request_id)
            elif match := JOB_PATH.match(parsed.path):
                job = self.server.artifact_repository.get_job(match.group(1))
                if job is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "job not found"}, request_id)
                else:
                    self._json(HTTPStatus.OK, job, request_id)
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

    def do_POST(self) -> None:
        request_id = str(uuid4())
        parsed = urlparse(self.path)
        if parsed.path == "/api/artifacts/snapshots":
            self._submit_snapshot_artifact(parsed, request_id)
            return
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

    def _submit_snapshot_artifact(self, parsed: Any, request_id: str) -> None:
        try:
            if self.headers.get_content_type() != "application/zip":
                raise ValidationError("Content-Type must be application/zip")
            query = parse_qs(parsed.query)
            project = query.get("project", ["demo-store"])[0]
            idempotency_key = self.headers.get("X-Idempotency-Key", "")
            baseline_build_id = self.headers.get("X-Baseline-Build-Id")
            result = self.server.artifact_service.submit_snapshots(
                project=project,
                idempotency_key=idempotency_key,
                baseline_build_id=baseline_build_id,
                content_length=self._content_length(),
                stream=cast(BinaryIO, self.rfile),
                provided_api_key=self.headers.get("X-API-Key"),
            )
            self._json(
                HTTPStatus.ACCEPTED,
                {
                    "build_id": result.build_id,
                    "job_id": result.job_id,
                    "status": result.status,
                    "replayed": result.replayed,
                    "sha256": result.sha256,
                    "size_bytes": result.size_bytes,
                },
                request_id,
            )
        except UnauthorizedError as exc:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": str(exc)}, request_id)
        except ArtifactTooLargeError as exc:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": str(exc)}, request_id)
        except (ArtifactStorageError, ValidationError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)}, request_id)
        except Exception:
            LOGGER.exception("artifact_submission_failed", extra={"request_id": request_id})
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"}, request_id)

    def _read_json(self) -> Any:
        length = self._content_length()
        if length <= 0 or length > self.server.settings.max_payload_bytes:
            raise ValidationError("request body has an invalid size")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _content_length(self) -> int:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValidationError("Content-Length is required")
        length = int(raw_length)
        if length <= 0:
            raise ValidationError("request body has an invalid size")
        return length

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


def create_http_server(
    service: TelemetryService,
    settings: Settings,
    artifact_service: ArtifactService | None = None,
    artifact_repository: ArtifactRepository | None = None,
) -> TraceHarborHTTPServer:
    repository = artifact_repository or ArtifactRepository(settings.database_path)
    artifacts = artifact_service or ArtifactService(
        repository,
        LocalArtifactStore(settings.artifact_directory),
        settings.api_key,
        max_artifact_bytes=settings.max_artifact_bytes,
        max_attempts=settings.artifact_job_max_attempts,
    )
    return TraceHarborHTTPServer(
        (settings.host, settings.port), service, artifacts, repository, settings
    )
