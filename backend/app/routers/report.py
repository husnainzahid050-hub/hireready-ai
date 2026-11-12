"""Report, share-link, email and delete-my-data endpoints (SPEC 7, Phase 5).

Security (docs/SECURITY.md):
- Every session-scoped endpoint checks ownership first (guest token; same 404 for "missing",
  "not yours" and "expired").
- A report is built only after the interview is completed (409 otherwise), once per session
  (the `reports` row is the lock), and only a fresh build is charged (rate limit + quota "report").
- Share links: 32 random bytes (`secrets.token_urlsafe`), revocable, served by a public endpoint
  that returns a redacted copy (no session id, no CV text, no email; emails / phone numbers said in
  answers are masked) with `X-Robots-Tag: noindex` and `Cache-Control: no-store`.
- Email is OFF (503 `email_not_configured`) until RESEND_API_KEY + EMAIL_FROM are set. The
  address and the report content are never logged.
- DELETE /sessions/{id} removes the session row; every table cascades from it.
"""

import re
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import get_settings
from app.core.errors import AI_UNAVAILABLE_MESSAGE, AppError
from app.core.logging import get_logger
from app.core.quotas import consume_quota
from app.core.rate_limit import enforce_rate_limit
from app.core.security import hash_token
from app.core.sse import BudgetExceededError, Event, paced, sse
from app.db.client import SupabaseRest, get_db
from app.db.repositories import get_owned_session
from app.routers.sessions import NO_TOKEN, GuestToken
from app.schemas.report import (
    EmailRequest,
    EmailResponse,
    Report,
    ReportResponse,
    ShareInfo,
    ShareRequest,
)
from app.services import email as email_service
from app.services import report as service
from app.services.llm import LLMError, get_llm

log = get_logger(__name__)
router = APIRouter(prefix="/sessions/{session_id}", tags=["report"])
public_router = APIRouter(prefix="/reports", tags=["report"])

REPORT_BUDGET_S = 55.0  # Vercel stops the function at 60 s
SLOW_AFTER_S = 15.0
SLOW_EVENT: Event = (
    "status",
    {
        "step": "slow",
        "message": "This is taking longer than usual because our AI provider is busy. "
        "Still working…",
    },
)
SHARE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
NOINDEX_HEADERS = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"}


def _require_completed(session: dict[str, Any]) -> None:
    if session.get("status") != "completed":
        raise AppError(
            "interview_not_completed",
            "Finish the mock interview first; the report is built from your answers.",
            status_code=409,
        )


def _share(token: str | None) -> ShareInfo:
    return ShareInfo(active=bool(token), token=token, path=f"/r/{token}" if token else None)


def _stream(
    events: AsyncIterator[Event], on_close: Callable[[], Awaitable[None]] | None = None
) -> StreamingResponse:
    async def body() -> AsyncIterator[str]:
        try:
            async for event, payload in events:
                yield sse(event, payload)
        except AppError as exc:
            yield sse("error", {"code": exc.code, "message": exc.message})
        except BudgetExceededError:
            log.warning("report_timeout")
            yield sse("error", {"code": "report_timeout", "message": AI_UNAVAILABLE_MESSAGE})
        except LLMError:
            log.exception("report_llm_failed")
            yield sse("error", {"code": "ai_unavailable", "message": AI_UNAVAILABLE_MESSAGE})
        except Exception:
            log.exception("report_failed")
            yield sse(
                "error",
                {"code": "internal_error", "message": "The report failed. Please try again."},
            )
        finally:
            if on_close is not None:
                await on_close()

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


async def _single(event: str, payload: dict[str, Any]) -> AsyncIterator[Event]:
    yield event, payload


async def _ready_report(db: SupabaseRest, session_id: UUID) -> service.ReportRow:
    row = await service.load_row(db, session_id)
    if row is None or row.report is None:
        raise AppError("report_not_ready", "Generate your report first.", status_code=409)
    return row


# ------------------------------------------------------------------ report


@router.post("/report")
async def generate_report(
    session_id: UUID, request: Request, token: GuestToken = NO_TOKEN
) -> StreamingResponse:
    db = get_db()
    session = await get_owned_session(db, session_id, token)
    _require_completed(session)

    row = await service.load_row(db, session_id)
    if row and row.report:  # cached: free, no LLM call
        return _stream(_single("done", row.report.model_dump(mode="json")))
    if not await service.claim(db, session_id):
        return _stream(service.wait_for_report(db, session_id))

    async def release() -> None:
        try:
            await service.release(db, session_id)
        except Exception:  # a stuck placeholder expires on its own after CLAIM_TTL_S
            log.exception("report_release_failed")

    try:
        await enforce_rate_limit(request, "report")
        await consume_quota(db, session_id, "report")
    except Exception:
        await release()
        raise
    llm = get_llm()
    events = paced(
        service.build_report(db, llm, session),
        budget_s=REPORT_BUDGET_S,
        slow_after_s=SLOW_AFTER_S,
        slow_event=SLOW_EVENT,
        fallbacks=lambda: llm.fallbacks,
    )
    return _stream(events, on_close=release)


@router.get("/report", response_model=ReportResponse)
async def get_report(session_id: UUID, token: GuestToken = NO_TOKEN) -> ReportResponse:
    db = get_db()
    session = await get_owned_session(db, session_id, token)
    _require_completed(session)
    row = await service.load_row(db, session_id)
    return ReportResponse(
        status="none" if row is None else row.state,
        report=row.report if row else None,
        share=_share(row.share_token if row and row.report else None),
        email_configured=email_service.email_configured(),
        emailed_at=row.emailed_at if row else None,
    )


# ------------------------------------------------------------------ share link


@router.post("/report/share", response_model=ShareInfo)
async def share_report(
    session_id: UUID, body: ShareRequest | None = None, token: GuestToken = NO_TOKEN
) -> ShareInfo:
    db = get_db()
    await get_owned_session(db, session_id, token)
    row = await _ready_report(db, session_id)
    action = body.action if body else "create"
    if action == "revoke":
        await db.update("reports", {"session_id": f"eq.{session_id}"}, {"share_token": None})
        log.info("report_share_revoked", extra={"extra_fields": {"session_id": str(session_id)}})
        return _share(None)
    if row.share_token:  # idempotent: one active link per report
        return _share(row.share_token)
    share_token = secrets.token_urlsafe(32)  # 256 bits, 43 URL-safe chars
    await db.update("reports", {"session_id": f"eq.{session_id}"}, {"share_token": share_token})
    log.info("report_share_created", extra={"extra_fields": {"session_id": str(session_id)}})
    return _share(share_token)


@public_router.get("/shared/{share_token}")
async def shared_report(share_token: str) -> JSONResponse:
    if not SHARE_TOKEN_RE.fullmatch(share_token):
        raise AppError("report_not_found", "This link is invalid or was revoked.", 404)
    db = get_db()
    rows = await db.select(
        "reports",
        {"select": "session_id,report", "share_token": f"eq.{share_token}", "limit": "1"},
    )
    if not rows or (rows[0].get("report") or {}).get("state") != "ready":
        raise AppError("report_not_found", "This link is invalid or was revoked.", 404)
    sessions = await db.select(
        "sessions",
        {"select": "expires_at", "id": f"eq.{rows[0]['session_id']}", "limit": "1"},
    )
    if not sessions or datetime.fromisoformat(sessions[0]["expires_at"]) < datetime.now(UTC):
        raise AppError("report_not_found", "This link is invalid or was revoked.", 404)
    report = Report.model_validate(rows[0]["report"])
    return JSONResponse({"report": service.shared_view(report)}, headers=NOINDEX_HEADERS)


# ------------------------------------------------------------------ email


@router.post("/email", response_model=EmailResponse)
async def email_report(
    session_id: UUID,
    request: Request,
    body: EmailRequest | None = None,
    token: GuestToken = NO_TOKEN,
) -> EmailResponse:
    db = get_db()
    await get_owned_session(db, session_id, token)
    provider = email_service.get_email_provider()
    if provider is None:
        raise AppError(
            "email_not_configured",
            "Email isn't set up on this server yet. Use the share link or Save as PDF instead.",
            status_code=503,
        )
    row = await _ready_report(db, session_id)
    assert row.report is not None  # noqa: S101
    to = body.email if body and body.email else None
    if to is None:
        found = await db.select(
            "sessions", {"select": "email", "id": f"eq.{session_id}", "limit": "1"}
        )
        to = found[0].get("email") if found else None
    if not to:
        raise AppError("email_required", "Enter the email address to send the report to.", 422)
    await enforce_rate_limit(request, "email")
    await consume_quota(db, session_id, "email")
    base = get_settings().app_base_url.rstrip("/")
    link = f"{base}/session/{session_id}/report"
    share_link = f"{base}/r/{row.share_token}" if row.share_token else None
    subject, html, text = email_service.render_report_email(row.report, link, share_link)
    # Same report + same recipient within 24 h = one email, even on a double click or a retry
    # after a timeout. The key holds a hash of the address, never the address itself.
    to_hash = hash_token(to.strip().lower())[:16]
    key = f"report/{session_id}/{to_hash}/{row.report.generated_at}"
    try:
        await provider.send(to=to, subject=subject, html=html, text=text, idempotency_key=key)
    except email_service.EmailError as exc:
        raise AppError(
            "email_failed", "We couldn't send the email. Please try again later.", 502
        ) from exc
    sent_at = datetime.now(UTC).isoformat()
    await db.update("reports", {"session_id": f"eq.{session_id}"}, {"emailed_at": sent_at})
    log.info("report_emailed", extra={"extra_fields": {"session_id": str(session_id)}})
    return EmailResponse(sent=True, emailed_at=sent_at)


# ------------------------------------------------------------------ delete my data


@router.delete("", status_code=204)
async def delete_session(session_id: UUID, token: GuestToken = NO_TOKEN) -> Response:
    """Delete the session and everything that belongs to it (all tables cascade from sessions):
    documents, CV chunks, analysis, questions, answers, interview state, report + share link,
    reminders, quota counters."""
    db = get_db()
    await get_owned_session(db, session_id, token)
    await db.delete("sessions", {"id": f"eq.{session_id}"})
    log.info("session_deleted", extra={"extra_fields": {"session_id": str(session_id)}})
    return Response(status_code=204)
