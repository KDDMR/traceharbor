"""Validation and normalization for incoming telemetry events."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from uuid import UUID, uuid4


ALLOWED_TYPES = {"error", "message", "transaction"}
ALLOWED_LEVELS = {"debug", "info", "warning", "error", "fatal"}
PROJECT_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")


class ValidationError(ValueError):
    """Raised when a telemetry event does not match the public contract."""


def _iso_timestamp(value: Any) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if not isinstance(value, str):
        raise ValidationError("timestamp must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("timestamp must be a valid ISO-8601 string") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _event_id(value: Any) -> str:
    if value is None:
        return str(uuid4())
    if not isinstance(value, str):
        raise ValidationError("event_id must be a UUID string")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValidationError("event_id must be a valid UUID") from exc


def _string_map(name: str, value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError(f"{name} must be an object")
    if len(value) > 50:
        raise ValidationError(f"{name} may contain at most 50 entries")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, (str, int, float, bool)):
            raise ValidationError(f"{name} keys and values must be scalar")
        result[key[:100]] = str(item)[:500]
    return result


def validate_event(payload: Any) -> dict[str, Any]:
    """Return a normalized copy of an untrusted event payload."""
    if not isinstance(payload, dict):
        raise ValidationError("event must be a JSON object")

    event_type = payload.get("type")
    if event_type not in ALLOWED_TYPES:
        raise ValidationError(f"type must be one of: {', '.join(sorted(ALLOWED_TYPES))}")

    project = payload.get("project")
    if not isinstance(project, str) or not PROJECT_PATTERN.fullmatch(project):
        raise ValidationError("project must be 2-64 letters, numbers, underscores or dashes")

    level = payload.get("level", "error" if event_type == "error" else "info")
    if level not in ALLOWED_LEVELS:
        raise ValidationError(f"level must be one of: {', '.join(sorted(ALLOWED_LEVELS))}")

    message = payload.get("message", "")
    if not isinstance(message, str):
        raise ValidationError("message must be a string")
    message = message.strip()[:4_000]

    exception: dict[str, Any] | None = None
    if event_type == "error":
        raw_exception = payload.get("exception")
        if not isinstance(raw_exception, dict):
            raise ValidationError("error events require an exception object")
        exception_type = raw_exception.get("type")
        exception_value = raw_exception.get("value", "")
        frames = raw_exception.get("frames", [])
        if not isinstance(exception_type, str) or not exception_type.strip():
            raise ValidationError("exception.type is required")
        if not isinstance(exception_value, str) or not isinstance(frames, list):
            raise ValidationError("exception.value must be a string and frames must be an array")
        normalized_frames: list[dict[str, Any]] = []
        for frame in frames[-50:]:
            if not isinstance(frame, dict):
                continue
            normalized_frames.append(
                {
                    "filename": str(frame.get("filename", ""))[:500],
                    "function": str(frame.get("function", ""))[:200],
                    "lineno": int(frame.get("lineno", 0) or 0),
                }
            )
        exception = {
            "type": exception_type.strip()[:200],
            "value": exception_value[:4_000],
            "frames": normalized_frames,
        }

    transaction = payload.get("transaction")
    duration_ms = payload.get("duration_ms")
    if event_type == "transaction":
        if not isinstance(transaction, str) or not transaction.strip():
            raise ValidationError("transaction events require a transaction name")
        if not isinstance(duration_ms, (int, float)) or duration_ms < 0:
            raise ValidationError("transaction events require a non-negative duration_ms")

    fingerprint = payload.get("fingerprint")
    if fingerprint is not None and not isinstance(fingerprint, (str, list)):
        raise ValidationError("fingerprint must be a string or an array")

    return {
        "event_id": _event_id(payload.get("event_id")),
        "type": event_type,
        "project": project,
        "timestamp": _iso_timestamp(payload.get("timestamp")),
        "level": level,
        "message": message,
        "exception": exception,
        "transaction": transaction.strip()[:500] if isinstance(transaction, str) else None,
        "duration_ms": round(float(duration_ms), 3) if isinstance(duration_ms, (int, float)) else None,
        "tags": _string_map("tags", payload.get("tags")),
        "context": payload.get("context", {}) if isinstance(payload.get("context", {}), dict) else {},
        "release": str(payload.get("release", "unknown"))[:200],
        "environment": str(payload.get("environment", "development"))[:100],
        "fingerprint": fingerprint,
    }
