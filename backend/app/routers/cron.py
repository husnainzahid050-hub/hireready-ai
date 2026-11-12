"""Vercel Cron endpoints (SPEC 6.7): cleanup of expired guest data and daily reminders.

Schedules live in `backend/vercel.json` (Hobby plan: once a day, about +-1 h precision). When the
`CRON_SECRET` env var is set on the project, Vercel sends `Authorization: Bearer <CRON_SECRET>`
with every cron invocation; we compare it in constant time and FAIL CLOSED: no secret configured
-> 503, wrong or missing header -> 401. Both jobs are idempotent (Vercel may retry, and the time
precision means a run can land in a different hour).
"""

import hmac
import time
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.rate_limit import enforce_rate_limit
from app.db.client import get_db
from app.services import email as email_service
from app.services import reminders

log = get_logger(__name__)
router = APIRouter(prefix="/cron", tags=["cron"])

CLEANUP_BATCH = 200  # sessions per SQL call; bounded so a backlog can't time out the function
CLEANUP_MAX_BATCHES = 10
CLEANUP_BUDGET_S = 40.0

Authorization = Annotated[str | None, Header()]


def require_cron_secret(authorization: str | None) -> None:
    secret = get_settings().cron_secret
    if secret is None or not secret.get_secret_value():
        raise AppError("cron_not_configured", "Cron jobs are not configured.", status_code=503)
    expected = f"Bearer {secret.get_secret_value()}".encode()
    if not authorization or not hmac.compare_digest(authorization.encode(), expected):
        log.warning("cron_unauthorized")
        raise AppError("unauthorized", "Missing or invalid cron credentials.", status_code=401)


async def _record(name: str, stats: dict[str, Any]) -> None:
    try:
        await get_db().insert("cron_runs", [{"name": name, "stats": stats}])
    except Exception:  # bookkeeping must never fail the job itself
        log.exception("cron_record_failed")


@router.get("/cleanup")
async def cleanup(authorization: Authorization = None) -> dict[str, Any]:
    """Delete expired sessions and everything in them (7-day guest retention), expired reminder
    rows and old cron_runs. The SQL function records each batch in `cron_runs`."""
    require_cron_secret(authorization)
    db = get_db()
    deadline = time.monotonic() + CLEANUP_BUDGET_S
    totals: dict[str, int] = {}
    batches = 0
    more = True
    while more and batches < CLEANUP_MAX_BATCHES and time.monotonic() < deadline:
        stats = await db.rpc("cleanup_expired", {"p_batch": CLEANUP_BATCH})
        batches += 1
        more = bool(stats.get("more"))
        for key, value in stats.items():
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] = totals.get(key, 0) + value
    log.info("cron_cleanup", extra={"extra_fields": {**totals, "batches": batches, "more": more}})
    return {"ok": True, "batches": batches, "more": more, "deleted": totals}


@router.get("/reminders")
async def send_reminders(authorization: Authorization = None) -> dict[str, Any]:
    require_cron_secret(authorization)
    provider = email_service.get_email_provider()
    if provider is None or not reminders.reminders_configured():
        log.info("cron_reminders_disabled")
        return {"ok": True, "enabled": False}
    stats = await reminders.send_due(get_db(), provider)
    log.info("cron_reminders", extra={"extra_fields": stats})
    await _record("reminders", stats)
    return {"ok": True, "enabled": True, **stats}


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    """Public proof that the cleanup runs (for the Engineering / privacy pages): when it last ran
    and how many sessions it deleted. No IDs, no personal data."""
    await enforce_rate_limit(request, "public_status")
    rows = await get_db().select(
        "cron_runs",
        {"select": "name,ran_at,stats", "order": "ran_at.desc", "limit": "20"},
    )
    out: dict[str, Any] = {}
    for row in rows:
        if row["name"] not in out:
            stats = row.get("stats") or {}
            out[row["name"]] = {
                "ran_at": row["ran_at"],
                "sessions_deleted": stats.get("sessions"),
                "emails_sent": stats.get("sent"),
            }
    return {"last_runs": out}
