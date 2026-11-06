"""Structured JSON logging with a per-request ID.

Rule: never log CV text, transcripts, or emails. Log IDs only.
The formatter also enforces this as a safety net: email addresses are masked and long string
values (which could be pasted CV / transcript text) are truncated before anything is written.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MAX_LOG_STR = 200  # a log value longer than this is almost certainly content, not an ID
_REQUEST_ID_RE = re.compile(r"[^A-Za-z0-9._:-]")


def redact(value: object) -> object:
    """Mask emails and truncate long strings (recursively for dicts/lists)."""
    if isinstance(value, str):
        masked = EMAIL_RE.sub("[email]", value)
        if len(masked) > MAX_LOG_STR:
            return f"{masked[:MAX_LOG_STR]}…[truncated {len(masked) - MAX_LOG_STR} chars]"
        return masked
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


def safe_request_id(raw: str | None) -> str | None:
    """Client-supplied X-Request-ID: keep only a short, header-safe token (or None)."""
    if not raw:
        return None
    cleaned = _REQUEST_ID_RE.sub("", raw)[:64]
    return cleaned or None


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
            "request_id": request_id_var.get(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update({k: redact(v) for k, v in extra.items()})
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
