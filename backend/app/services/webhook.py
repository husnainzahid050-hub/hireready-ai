"""Outbound webhook on report completion (SPEC 6.7), signed per Standard Webhooks.

Standard Webhooks (https://www.standardwebhooks.com/, used by Svix and others) instead of a
home-made header scheme, so any receiver library can verify it:
- `webhook-id`: a stable event id (the same on every retry, for dedupe)
- `webhook-timestamp`: unix seconds (receivers reject anything outside +-5 minutes: replay guard)
- `webhook-signature`: `v1,<base64(HMAC-SHA256(key, "{id}.{timestamp}.{raw body}"))>`
  where key = base64-decoded part after `whsec_` (or the raw secret bytes if it has no prefix).

Payload is minimal on purpose: no CV text, transcripts, answers or email address. Just the event
type, the session id, role title, readiness score + band and timestamps.

Delivery never blocks or fails the report: it runs after the report is saved and streamed, has a
5 s timeout per attempt and 3 attempts with backoff inside a 15 s overall budget, and every error is
swallowed (logged as status code / error type only). Verification snippet: docs/SECURITY.md.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.http import get_http_client, request_with_retry
from app.core.logging import get_logger
from app.schemas.report import Report

log = get_logger(__name__)

ATTEMPT_TIMEOUT_S = 5.0
TOTAL_BUDGET_S = 15.0
TOLERANCE_S = 300  # what receivers should accept (Standard Webhooks recommendation)


def secret_key(secret: str) -> bytes:
    if secret.startswith("whsec_"):
        return base64.b64decode(secret.removeprefix("whsec_"))
    return secret.encode("utf-8")


def sign(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    signed = f"{msg_id}.{timestamp}.".encode() + body
    digest = hmac.new(secret_key(secret), signed, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def verify(secret: str, headers: dict[str, str], body: bytes, *, now: float | None = None) -> bool:
    """Receiver-side check (used by the tests and shown in the docs)."""
    try:
        msg_id, ts = headers["webhook-id"], int(headers["webhook-timestamp"])
        sigs = headers["webhook-signature"].split()
    except (KeyError, ValueError):
        return False
    if abs((now if now is not None else time.time()) - ts) > TOLERANCE_S:
        return False
    expected = sign(secret, msg_id, ts, body)
    return any(hmac.compare_digest(expected, s) for s in sigs)


def report_completed_payload(session_id: str, report: Report) -> dict[str, Any]:
    return {
        "type": "report.completed",
        "timestamp": report.generated_at,
        "data": {
            "session_id": session_id,
            "role_title": report.role_title,
            "readiness_score": report.readiness.score,
            "band": report.readiness.band,
            "band_label": report.readiness.band_label,
            "questions": len(report.questions),
            "generated_at": report.generated_at,
        },
    }


async def deliver(
    payload: dict[str, Any],
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
    msg_id: str | None = None,
    sleep: Any = asyncio.sleep,
) -> int | None:
    """POST the signed event. Returns the final HTTP status, or None (off or failed).
    Never raises."""
    s = settings or get_settings()
    if not s.webhook_enabled:
        return None
    assert s.outbound_webhook_url and s.outbound_webhook_secret  # noqa: S101 (webhook_enabled)
    url, secret = s.outbound_webhook_url, s.outbound_webhook_secret.get_secret_value()
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    event_id = msg_id or f"msg_{uuid.uuid4().hex}"
    http = client or get_http_client()

    async def send() -> httpx.Response:
        ts = int(time.time())  # fresh timestamp per attempt; the id stays the same
        return await http.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "HireReady-Webhook/1",
                "webhook-id": event_id,
                "webhook-timestamp": str(ts),
                "webhook-signature": sign(secret, event_id, ts, body),
            },
            timeout=ATTEMPT_TIMEOUT_S,
        )

    try:
        async with asyncio.timeout(TOTAL_BUDGET_S):
            resp = await request_with_retry(
                send, what="webhook", max_attempts=3, base_delay=0.5, max_delay=4.0, sleep=sleep
            )
    except Exception as exc:  # never let a receiver break the report
        log.warning("webhook_failed", extra={"extra_fields": {"error": type(exc).__name__}})
        return None
    level = log.info if resp.status_code < 300 else log.warning
    level("webhook_sent", extra={"extra_fields": {"status": resp.status_code}})
    return resp.status_code
