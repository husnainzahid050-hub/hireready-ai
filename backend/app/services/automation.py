"""What happens after a report is built (SPEC 6.7): webhook, report email, reminder opt-in.

`after_report(events, db, session)` wraps the report SSE stream. When the fresh `done` event goes
by, it starts `on_report_completed` as a task and then passes the event on, so the user sees the
report first and nothing here can delay or fail it. Each step is independent and swallows its
own errors (logged with IDs only):

1. Outbound webhook `report.completed` (Standard Webhooks, minimal payload): `app.services.webhook`.
2. Report email, only if the user ticked "Email me my report" at /start (`sessions.email_opt_in`)
   and email is configured. Same per-session quota and per-recipient limit as the button.
3. Reminder opt-in, only if the user ticked "Send me 7 daily prep emails" (`reminders_opt_in`):
   creates a PENDING reminder and sends the confirmation email (double opt-in).

Serverless note: the task is started before the `done` event is yielded and the generator then
waits for it (bounded), so on Vercel it normally finishes inside the same invocation even if the
browser closes the stream right after `done`.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.quotas import QuotaExceededError, consume_quota
from app.core.rate_limit import allow
from app.core.security import hash_token
from app.core.sse import Event
from app.db.client import SupabaseRest
from app.schemas.report import Report
from app.services import email as email_service
from app.services import reminders, webhook

log = get_logger(__name__)

WAIT_S = 20.0  # webhook budget (15 s) + two emails
_tasks: set[asyncio.Task[None]] = set()  # strong refs so running tasks aren't garbage-collected


async def _contact(db: SupabaseRest, session_id: str) -> dict[str, Any]:
    rows = await db.select(
        "sessions",
        {
            "select": "email,email_opt_in,reminders_opt_in",
            "id": f"eq.{session_id}",
            "limit": "1",
        },
    )
    return rows[0] if rows else {}


async def _email_report(db: SupabaseRest, session_id: str, to: str, report: Report) -> None:
    provider = email_service.get_email_provider()
    if provider is None:
        return
    if not await allow("email_recipient", subject=hash_token(to.strip().lower())[:32]):
        return
    try:
        await consume_quota(db, UUID(session_id), "email")
    except QuotaExceededError:
        return
    base = get_settings().app_base_url.rstrip("/")
    subject, html, text = email_service.render_report_email(
        report, f"{base}/session/{session_id}/report"
    )
    key = f"report/{session_id}/{hash_token(to.strip().lower())[:16]}/{report.generated_at}"
    await provider.send(to=to, subject=subject, html=html, text=text, idempotency_key=key)
    await db.update(
        "reports", {"session_id": f"eq.{session_id}"}, {"emailed_at": datetime.now(UTC).isoformat()}
    )
    log.info("report_auto_emailed", extra={"extra_fields": {"session_id": session_id}})


async def _start_reminders(db: SupabaseRest, session_id: str, to: str, report: Report) -> None:
    provider = email_service.get_email_provider()
    if provider is None:
        return
    result = await reminders.subscribe(
        db,
        provider,
        session_id=session_id,
        email=to,
        role_title=report.role_title,
        plan=report.prep_plan,
    )
    log.info("reminder_subscribe", extra={"extra_fields": {"session_id": session_id, "r": result}})


async def on_report_completed(db: SupabaseRest, session: dict[str, Any], report: Report) -> None:
    sid = str(session["id"])
    steps: list[tuple[str, Any]] = [
        ("webhook", webhook.deliver(webhook.report_completed_payload(sid, report)))
    ]
    try:
        contact = await _contact(db, sid)
    except Exception:  # e.g. migration 07 not applied yet: no reminders_opt_in column
        log.exception("automation_contact_failed")
        contact = {}
    to = contact.get("email")
    if to and contact.get("email_opt_in"):
        steps.append(("report_email", _email_report(db, sid, to, report)))
    if to and contact.get("reminders_opt_in"):
        steps.append(("reminders", _start_reminders(db, sid, to, report)))
    results = await asyncio.gather(*(c for _, c in steps), return_exceptions=True)
    for (name, _), result in zip(steps, results, strict=True):
        if isinstance(result, BaseException):
            log.warning(
                "automation_step_failed",
                extra={"extra_fields": {"step": name, "error": type(result).__name__}},
            )


def start(db: SupabaseRest, session: dict[str, Any], report: Report) -> asyncio.Task[None]:
    task = asyncio.create_task(on_report_completed(db, session, report))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def after_report(
    events: AsyncIterator[Event], db: SupabaseRest, session: dict[str, Any]
) -> AsyncIterator[Event]:
    """Pass the report stream through; kick off automation on the fresh `done` event."""
    task: asyncio.Task[None] | None = None
    async for event, payload in events:
        if event == "done" and task is None:
            try:
                task = start(db, session, Report.model_validate(payload))
            except ValidationError:
                log.warning("automation_bad_report")
        yield event, payload
    if task is not None:
        # The client already has the report; give the automation a bounded chance to finish
        # inside this invocation. shield(): a slow webhook is abandoned here, not cancelled.
        try:
            await asyncio.wait_for(asyncio.shield(task), WAIT_S)
        except TimeoutError:
            log.warning("automation_slow")
