"""Mock interview endpoints (text mode). Each POST advances the interview by exactly one turn."""

from uuid import UUID

from fastapi import APIRouter

from app.db.client import get_db
from app.db.repositories import get_owned_session
from app.routers.sessions import NO_TOKEN, GuestToken
from app.schemas.interview import AnswerRequest, InterviewTurn, StartInterviewRequest
from app.services import interview as service
from app.services.embeddings import get_embedder
from app.services.llm import get_llm

router = APIRouter(prefix="/sessions/{session_id}/interview", tags=["interview"])


@router.post("/start", response_model=InterviewTurn)
async def start(
    session_id: UUID, body: StartInterviewRequest | None = None, token: GuestToken = NO_TOKEN
) -> InterviewTurn:
    db = get_db()
    session = await get_owned_session(db, session_id, token)
    practice = body.practice_mode if body else False
    return await service.start_interview(db, get_llm(), get_embedder(), session, practice)


@router.get("", response_model=InterviewTurn)
async def current(session_id: UUID, token: GuestToken = NO_TOKEN) -> InterviewTurn:
    db = get_db()
    session = await get_owned_session(db, session_id, token)
    return await service.get_interview(db, session)


# Phase 4 (voice) will accept multipart audio here too: transcribe, then call the same
# service.submit_answer with the transcript (+ speech metrics).
@router.post("/answer", response_model=InterviewTurn)
async def answer(
    session_id: UUID, body: AnswerRequest, token: GuestToken = NO_TOKEN
) -> InterviewTurn:
    db = get_db()
    session = await get_owned_session(db, session_id, token)
    return await service.submit_answer(
        db, get_llm(), get_embedder(), session, body.question_id, body.text
    )
