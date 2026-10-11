"""Privacy filtering, issue grouping and derived event fields."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .models import validate_event


SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credit_card",
}
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
NUMBER_PATTERN = re.compile(r"\b\d{2,}\b")
UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b")


def redact(value: Any, key: str = "") -> Any:
    """Recursively remove common credentials and direct email identifiers."""
    if key.lower() in SENSITIVE_KEYS:
        return "[Filtered]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value[:100]]
    if isinstance(value, str):
        return EMAIL_PATTERN.sub("[email]", value)
    return value


def _stable_message(message: str) -> str:
    normalized = UUID_PATTERN.sub("<uuid>", message.lower())
    return NUMBER_PATTERN.sub("<number>", normalized).strip()


def issue_fingerprint(event: dict[str, Any]) -> str | None:
    """Build a stable issue key for errors and messages; transactions are ungrouped."""
    if event["type"] == "transaction":
        return None

    custom = event.get("fingerprint")
    if custom:
        material = custom if isinstance(custom, list) else [custom]
    elif event["type"] == "error":
        exception = event["exception"] or {}
        frames = exception.get("frames", [])
        top = frames[-1] if frames else {}
        material = [
            event["project"],
            exception.get("type", "Error"),
            top.get("filename", ""),
            top.get("function", ""),
        ]
    else:
        material = [event["project"], _stable_message(event["message"])]

    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:24]


def issue_title(event: dict[str, Any]) -> str:
    if event["type"] == "error":
        exception = event["exception"] or {}
        value = exception.get("value") or event["message"]
        return f"{exception.get('type', 'Error')}: {value}"[:500]
    return (event["message"] or "Untitled message")[:500]


def prepare_event(payload: Any) -> dict[str, Any]:
    """Apply the full ingest pipeline to one untrusted payload."""
    event = validate_event(redact(payload))
    event["fingerprint"] = issue_fingerprint(event)
    event["title"] = issue_title(event) if event["type"] != "transaction" else event["transaction"]
    return event
