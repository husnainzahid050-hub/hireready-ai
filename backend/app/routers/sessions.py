"""Session, document intake and gap-analysis endpoints."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.errors import AI_UNAVAILABLE_MESSAGE, AppError
from app.core.logging import get_logger
from app.core.quotas import consume_quota
from app.core.rate_limit import client_ip, enforce_rate_limit
from app.core.security import content_hash, hash_token, new_guest_token
from app.core.sse import BudgetExceededError, Event, paced, sse
from app.core.turnstile import require_human
from app.db.client import get_db
from app.db.repositories import get_owned_session, save_document
from app.demo.samples import DEMO_CV, DEMO_JD
from app.services.analysis import (
    claim_run,
    release_run,
    run_analysis,
    saved_analysis,
    wait_for_run,
)
from app.services.embeddings import get_embedder
from app.services.llm import LLMError, get_llm
from app.services.parsing import MAX_BYTES, extract_cv_text_async, validate_jd

log = get_logger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])

GuestToken = Annotated[str | None, Header(alias="X-Guest-Token")]
TurnstileToken = Annotated[str | None, Header(alias="X-Turnstile-Token")]
NO_TOKEN: str | None = None


class CreateSessionRequest(BaseModel):
    mode: Literal["voice", "text"] = "text"
    difficulty: Literal["junior", "mid"] = "junior"
    interview_type: Literal["technical", "behavioral", "mixed"] = "mixed"
    # Simple shape check (no extra dependency); real validation happens when we send email.
    email: str | None = Field(default=None, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    email_opt_in: bool = False
    consent: bool = Field(description="User accepted the privacy terms")


class CreateSessionResponse(BaseModel):
    session_id: UUID
    guest_token: str
    demo: bool
    status: str


@router.post("", response_model=CreateSessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    request: Request,
    demo: Annotated[bool, Query()] = False,
    turnstile_token: TurnstileToken = None,
) -> CreateSessionResponse:
    if not body.consent:
        raise AppError("consent_required", "Please accept the privacy terms to continue.")
    # Both are no-ops until UPSTASH_* / TURNSTILE_SECRET_KEY are configured (docs/SECURITY.md).
    await enforce_rate_limit(request, "session_create")
    await require_human(turnstile_token, client_ip(request))
    db = get_db()
    token = new_guest_token()
    row = await db.insert_returning(
        "sessions",
        {
            "guest_token_hash": hash_token(token),
            "mode": body.mode,
            "difficulty": body.difficulty,
            "interview_type": body.interview_type,
            "email": body.email,
            "email_opt_in": bool(body.email and body.email_opt_in),
            "is_demo": demo,
        },
    )
    sid = UUID(row["id"])
    if demo:
        await save_document(db, sid, "cv", DEMO_CV, content_hash(DEMO_CV))
        await save_document(db, sid, "jd", DEMO_JD, content_hash(DEMO_JD))
    log.info("session_created", extra={"extra_fields": {"session_id": str(sid), "demo": demo}})
    return CreateSessionResponse(session_id=sid, guest_token=token, demo=demo, status=row["status"])


class DocumentsResponse(BaseModel):
    cv_chars: int
    jd_chars: int


@router.post("/{session_id}/documents", response_model=DocumentsResponse)
async def upload_documents(
    session_id: UUID,
    cv: Annotated[UploadFile, File(description="CV as PDF or DOCX, max 2 MB")],
    # No Form max_length: validate_jd gives the specific `jd_too_long` error (QA B12), and
    # the 4.5 MB body limit already bounds the field.
    jd_text: Annotated[str, Form()],
    request: Request,
    token: GuestToken = NO_TOKEN,
) -> DocumentsResponse:
    db = get_db()
    await get_owned_session(db, session_id, token)
    jd = validate_jd(jd_text)
    await enforce_rate_limit(request, "upload")
    # Each upload deletes the old analysis, so uploads are capped too (else: upload/analyze loop).
    await consume_quota(db, session_id, "upload")
    data = await cv.read(MAX_BYTES + 1)  # read at most 1 byte past the limit
    cv_text = await extract_cv_text_async(data, cv.content_type)
    await save_document(db, session_id, "cv", cv_text, content_hash(cv_text))
    await save_document(db, session_id, "jd", jd, content_hash(jd))
    await db.update("sessions", {"id": f"eq.{session_id}"}, {"status": "created"})
    return DocumentsResponse(cv_chars=len(cv_text), jd_chars=len(jd))


ANALYSIS_BUDGET_S = 50.0  # Vercel stops the function at 60 s; leave time to report the error
SLOW_AFTER_S = 15.0
SLOW_EVENT: Event = (
    "status",
    {
        "step": "slow",
        "message": "This is taking longer than usual because our AI provider is busy. "
        "Still working…",
    },
)


def _sse_response(
    events: AsyncIterator[Event], on_close: Callable[[], Awaitable[None]] | None = None
) -> StreamingResponse:
    """Stream (event, payload) pairs as SSE. Failures become a final `error` event."""

    async def body() -> AsyncIterator[str]:
        try:
            async for event, payload in events:
                yield sse(event, payload)
        except AppError as exc:
            yield sse("error", {"code": exc.code, "message": exc.message})
        except BudgetExceededError:
            log.warning("analysis_timeout")
            yield sse("error", {"code": "analysis_timeout", "message": AI_UNAVAILABLE_MESSAGE})
        except LLMError:
            log.exception("analysis_llm_failed")
            yield sse("error", {"code": "ai_unavailable", "message": AI_UNAVAILABLE_MESSAGE})
        except Exception:
            log.exception("analysis_failed")
            yield sse(
                "error", {"code": "internal_error", "message": "Analysis failed. Please try again."}
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


@router.post("/{session_id}/analyze")
async def analyze(
    session_id: UUID, request: Request, token: GuestToken = NO_TOKEN
) -> StreamingResponse:
    db = get_db()
    session = await get_owned_session(db, session_id, token)

    # Already analyzed? Return the saved result instead of spending LLM calls again.
    saved = await saved_analysis(db, session_id)
    if saved:
        return _sse_response(_single("done", saved.model_dump()))

    # One run per session (QA bug B3): a second tab or a double click waits for the first run.
    if not await claim_run(db, session_id):
        return _sse_response(wait_for_run(db, session_id))

    async def release() -> None:
        try:
            await release_run(db, session_id)
        except Exception:  # a stuck claim expires on its own after CLAIM_TTL_S
            log.exception("analysis_release_failed")

    try:
        # Only a fresh run costs LLM calls, so only it is limited (429 as JSON).
        await enforce_rate_limit(request, "analyze")
        await consume_quota(db, session_id, "analysis")
    except Exception:
        await release()
        raise
    llm = get_llm()
    events = paced(
        run_analysis(db, llm, get_embedder(), session),
        budget_s=ANALYSIS_BUDGET_S,
        slow_after_s=SLOW_AFTER_S,
        slow_event=SLOW_EVENT,
        fallbacks=lambda: llm.fallbacks,
    )
    return _sse_response(events, on_close=release)


@router.get("/{session_id}/analysis")
async def get_analysis(session_id: UUID, token: GuestToken = NO_TOKEN) -> dict[str, Any]:
    db = get_db()
    session = await get_owned_session(db, session_id, token)
    saved = await saved_analysis(db, session_id)
    return {
        "session": {
            "id": session["id"],
            "status": session["status"],
            "mode": session["mode"],
            "difficulty": session["difficulty"],
            "interview_type": session["interview_type"],
            "is_demo": session["is_demo"],
        },
        # null until analyzed (200, not 404: "not analyzed yet" is a normal state, not an error)
        "analysis": saved.model_dump() if saved else None,
    }
