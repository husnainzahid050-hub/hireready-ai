"""Mock interview endpoints (text and voice answers). Each POST advances it by exactly one turn.

Security parity with the analysis endpoints (docs/SECURITY.md): ownership check first, then a
per-IP rate limit and a per-session quota, both charged only when a request really triggers an
LLM call (an idempotent re-start or a rejected answer is free). Turnstile guards session
creation, which every interview needs. Answers are capped by `AnswerRequest` (5,000 chars) and
fenced as <transcript> data in every prompt (`app.agents.interviewer.tools`).

Voice answers (multipart) are charged BEFORE transcription, because Whisper is the expensive
call there; the answerable-question check runs first so a stale upload is still free.
"""

from uuid import UUID

from fastapi import APIRouter, Request

from app.core.quotas import consume_quota
from app.core.rate_limit import enforce_rate_limit
from app.db.client import SupabaseRest, get_db
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


def _charge(request: Request, db: SupabaseRest, session_id: UUID, action: str) -> service.Charge:
    async def charge() -> None:
        await enforce_rate_limit(request, action)
        await consume_quota(db, session_id, action)

    return charge


@router.post("/start", response_model=InterviewTurn)
async def start(
    session_id: UUID,
    request: Request,
    body: StartInterviewRequest | None = None,
    token: GuestToken = NO_TOKEN,
) -> InterviewTurn:
    db = get_db()
    session = await get_owned_session(db, session_id, token)
    practice = body.practice_mode if body else False
    return await service.start_interview(
        db,
        get_llm(),
        get_embedder(),
        session,
        practice,
        charge=_charge(request, db, session_id, "interview_start"),
    )


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
    charge = _charge(request, db, session_id, "interview_answer")  # one budget for both modes
    if is_multipart(request):
        question_id, audio, mime = await voice.read_audio_form(request)
        return await voice.submit_voice_answer(
            db, get_llm(), get_embedder(), get_stt(), session, question_id, audio, mime,
            charge=charge,
        )  # fmt: skip
    body = await parse_json_answer(request)
    return await service.submit_answer(
        db,
        get_llm(),
        get_embedder(),
        session,
        body.question_id,
        body.text,
        charge=charge,
    )
