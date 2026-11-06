"""Mock interview endpoints (text and voice answers). Each POST advances it by exactly one turn."""

from uuid import UUID

from fastapi import APIRouter, Request

from app.core.quotas import consume_quota
from app.db.client import get_db
from app.db.repositories import get_owned_session
from app.routers.answer_body import ANSWER_OPENAPI, is_multipart, parse_json_answer
from app.routers.sessions import NO_TOKEN, GuestToken
from app.schemas.interview import InterviewTurn, StartInterviewRequest
from app.services import interview as service
from app.services import voice_answer as voice
from app.services.embeddings import get_embedder
from app.services.llm import get_llm
from app.services.stt import get_stt

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


# One endpoint, two body types (SPEC 7): JSON {question_id, text} for typed answers, or
# multipart {question_id, audio} for voice (Phase 4). Both end in service.submit_answer.
@router.post("/answer", response_model=InterviewTurn, openapi_extra=ANSWER_OPENAPI)
async def answer(session_id: UUID, request: Request, token: GuestToken = NO_TOKEN) -> InterviewTurn:
    db = get_db()
    session = await get_owned_session(db, session_id, token)
    # MERGE NOTE (voice branch): quota shared by text and voice answers; keep exactly one call.
    await consume_quota(db, session_id, "interview_answer")
    if is_multipart(request):
        question_id, audio, mime = await voice.read_audio_form(request)
        return await voice.submit_voice_answer(
            db, get_llm(), get_embedder(), get_stt(), session, question_id, audio, mime
        )
    body = await parse_json_answer(request)
    return await service.submit_answer(
        db, get_llm(), get_embedder(), session, body.question_id, body.text
    )
