"""Session, document intake and gap-analysis endpoints."""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.security import content_hash, hash_token, new_guest_token
from app.db.client import get_db
from app.db.repositories import get_owned_session, save_document
from app.demo.samples import DEMO_CV, DEMO_JD
from app.services.analysis import analysis_from_row, run_analysis
from app.services.embeddings import get_embedder
from app.services.llm import LLMError, get_llm
from app.services.parsing import MAX_BYTES, extract_cv_text, validate_jd

log = get_logger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])

GuestToken = Annotated[str | None, Header(alias="X-Guest-Token")]
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
    body: CreateSessionRequest, demo: Annotated[bool, Query()] = False
) -> CreateSessionResponse:
    if not body.consent:
        raise AppError("consent_required", "Please accept the privacy terms to continue.")
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
    jd_text: Annotated[str, Form(max_length=20_000)],
    token: GuestToken = NO_TOKEN,
) -> DocumentsResponse:
    db = get_db()
    await get_owned_session(db, session_id, token)
    jd = validate_jd(jd_text)
    data = await cv.read(MAX_BYTES + 1)  # read at most 1 byte past the limit
    cv_text = extract_cv_text(data, cv.content_type)
    await save_document(db, session_id, "cv", cv_text, content_hash(cv_text))
    await save_document(db, session_id, "jd", jd, content_hash(jd))
    await db.update("sessions", {"id": f"eq.{session_id}"}, {"status": "created"})
    return DocumentsResponse(cv_chars=len(cv_text), jd_chars=len(jd))


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/{session_id}/analyze")
async def analyze(session_id: UUID, token: GuestToken = NO_TOKEN) -> StreamingResponse:
    db = get_db()
    session = await get_owned_session(db, session_id, token)

    # Already analyzed? Return the saved result instead of spending LLM calls again.
    existing = await db.select("gap_analyses", {"select": "*", "session_id": f"eq.{session_id}"})

    async def stream() -> AsyncIterator[str]:
        if existing:
            yield _sse("done", analysis_from_row(existing[0]).model_dump())
            return
        try:
            async for event, payload in run_analysis(db, get_llm(), get_embedder(), session):
                yield _sse(event, payload)
        except AppError as exc:
            yield _sse("error", {"code": exc.code, "message": exc.message})
        except LLMError:
            log.exception("analysis_llm_failed")
            yield _sse(
                "error",
                {
                    "code": "ai_unavailable",
                    "message": "Our AI providers are busy right now. Please try again in a minute.",
                },
            )
        except Exception:
            log.exception("analysis_failed")
            yield _sse(
                "error", {"code": "internal_error", "message": "Analysis failed. Please try again."}
            )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}/analysis")
async def get_analysis(session_id: UUID, token: GuestToken = NO_TOKEN) -> dict[str, Any]:
    db = get_db()
    session = await get_owned_session(db, session_id, token)
    rows = await db.select("gap_analyses", {"select": "*", "session_id": f"eq.{session_id}"})
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
        "analysis": analysis_from_row(rows[0]).model_dump() if rows else None,
    }
