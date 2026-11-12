"""Reminder links (public, token-only) and the session-scoped opt-in endpoint.

Public endpoints take ONLY the reminder token from the email (no login, no guest token: the email
is often opened on another device). The token can confirm, mark a day done, restart or
unsubscribe; it never reveals the email address or opens the session.

GET never changes anything: mail security scanners pre-fetch links, and RFC 8058 says the GET of
an unsubscribe URL must not unsubscribe. Every action is a POST from a button on our page, except
the one-click unsubscribe, which mail clients POST directly with `List-Unsubscribe=One-Click`
(no confirmation step, always 200, idempotent).
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.rate_limit import enforce_rate_limit
from app.db.client import get_db
from app.db.repositories import get_owned_session
from app.routers.sessions import NO_TOKEN, GuestToken
from app.schemas.report import Report
from app.services import email as email_service
from app.services import reminders

log = get_logger(__name__)
router = APIRouter(tags=["reminders"])

PRIVATE_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Cache-Control": "private, no-store",
    "Referrer-Policy": "no-referrer",
}
GONE = "This reminder link has expired or you've already unsubscribed."


def _json(body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(body, headers=PRIVATE_HEADERS)


async def _row(request: Request, token: str) -> dict[str, Any]:
    await enforce_rate_limit(request, "reminder_link")
    row = await reminders.find_by_token(get_db(), token)
    if row is None:
        raise AppError("reminder_not_found", GONE, status_code=404)
    return row


@router.get("/reminders/{token}")
async def reminder_status(token: str, request: Request) -> JSONResponse:
    return _json(reminders.public_status(await _row(request, token)))


@router.post("/reminders/{token}/confirm")
async def confirm(token: str, request: Request) -> JSONResponse:
    row = await _row(request, token)
    updated = await reminders.confirm(get_db(), email_service.get_email_provider(), row)
    return _json(reminders.public_status(updated))


class DoneRequest(BaseModel):
    day: int = Field(ge=1, le=reminders.DAYS)


@router.post("/reminders/{token}/done")
async def mark_done(token: str, body: DoneRequest, request: Request) -> JSONResponse:
    row = await _row(request, token)
    return _json(reminders.public_status(await reminders.mark_done(get_db(), row, body.day)))


@router.post("/reminders/{token}/resume")
async def resume(token: str, request: Request) -> JSONResponse:
    row = await _row(request, token)
    return _json(reminders.public_status(await reminders.resume(get_db(), row)))


@router.get("/unsubscribe/{token}")
async def unsubscribe_status(token: str, request: Request) -> JSONResponse:
    """No side effects (scanner-safe): tells the page whether there is anything to stop."""
    await enforce_rate_limit(request, "reminder_link")
    row = await reminders.find_by_token(get_db(), token)
    return _json({"subscribed": row is not None})


@router.post("/unsubscribe/{token}")
async def unsubscribe(token: str, request: Request) -> JSONResponse:
    """RFC 8058 one-click target. Mail clients POST `List-Unsubscribe=One-Click`; we don't need
    the body. Always 200 so a retry or an old link never shows an error."""
    await enforce_rate_limit(request, "reminder_link")
    await reminders.unsubscribe(get_db(), token)
    return _json({"unsubscribed": True})


# ------------------------------------------------------------------ opt-in from the report page


class SubscribeRequest(BaseModel):
    email: str | None = Field(default=None, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SubscribeResponse(BaseModel):
    status: str  # "pending" (confirmation sent) | "exists"


@router.post("/sessions/{session_id}/reminders", response_model=SubscribeResponse)
async def subscribe(
    session_id: UUID,
    request: Request,
    body: SubscribeRequest | None = None,
    token: GuestToken = NO_TOKEN,
) -> SubscribeResponse:
    """Explicit opt-in after the report (the second, separate checkbox). Sends a confirmation
    email; daily emails start only after the person clicks it."""
    db = get_db()
    await get_owned_session(db, session_id, token)
    provider = email_service.get_email_provider()
    if provider is None or not reminders.reminders_configured():
        raise AppError(
            "reminders_not_configured", "Daily prep emails aren't set up on this server yet.", 503
        )
    rows = await db.select(
        "reports", {"select": "report", "session_id": f"eq.{session_id}", "limit": "1"}
    )
    report_data = rows[0].get("report") if rows else None
    if not report_data or report_data.get("state") != "ready":
        raise AppError("report_not_ready", "Generate your report first.", status_code=409)
    report = Report.model_validate(report_data)
    to = body.email if body and body.email else None
    if to is None:
        found = await db.select(
            "sessions", {"select": "email", "id": f"eq.{session_id}", "limit": "1"}
        )
        to = found[0].get("email") if found else None
    if not to:
        raise AppError("email_required", "Enter the email address for your daily prep emails.")
    await enforce_rate_limit(request, "reminder_subscribe")
    try:
        result = await reminders.subscribe(
            db,
            provider,
            session_id=str(session_id),
            email=to,
            role_title=report.role_title,
            plan=report.prep_plan,
        )
    except email_service.EmailError as exc:
        raise AppError(
            "email_failed", "We couldn't send the confirmation email. Please try again later.", 502
        ) from exc
    if result == "limited":
        raise AppError(
            "rate_limited",
            "We've sent enough email to that address today. Please try again tomorrow.",
            status_code=429,
            headers={"Retry-After": "3600"},
        )
    if result == "no_plan":
        raise AppError("no_plan", "This report has no 7-day plan to send.", status_code=409)
    return SubscribeResponse(status="exists" if result == "exists" else "pending")
