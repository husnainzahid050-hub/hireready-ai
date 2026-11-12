"""Interview service: load state -> run ONE graph turn -> persist -> build the API response.

Serverless-friendly: nothing is kept in memory between requests. The full graph state is a JSON
document in `interview_state`; questions and answers also go to their own tables (used by the
Phase 5 report). LangGraph is imported lazily so other endpoints don't pay its import time.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.errors import AppError, ai_unavailable
from app.core.logging import get_logger
from app.db.client import DatabaseError, SupabaseRest
from app.schemas.analysis import CVProfile, GapItem, JobProfile
from app.schemas.interview import (
    FeedbackOut,
    HistoryItem,
    InterviewTurn,
    LastAnswer,
    Progress,
    QuestionOut,
)
from app.schemas.speech import SpeechMetrics
from app.services.embeddings import Embedder
from app.services.llm import LLMClient, LLMError
from app.services.retrieval import Retriever

if TYPE_CHECKING:
    from app.agents.interviewer.state import AskedQuestion, InterviewState

log = get_logger(__name__)


# ------------------------------------------------------------------ loading


async def load_state(db: SupabaseRest, session_id: UUID) -> "InterviewState | None":
    from app.agents.interviewer.state import InterviewState

    rows = await db.select(
        "interview_state", {"select": "state", "session_id": f"eq.{session_id}", "limit": "1"}
    )
    return InterviewState.model_validate(rows[0]["state"]) if rows else None


async def load_inputs(
    db: SupabaseRest, session_id: UUID
) -> tuple[CVProfile, JobProfile, list[GapItem]]:
    docs, analysis = await asyncio.gather(
        db.select("documents", {"select": "kind,structured", "session_id": f"eq.{session_id}"}),
        db.select("gap_analyses", {"select": "gaps", "session_id": f"eq.{session_id}"}),
    )
    structured = {d["kind"]: d.get("structured") for d in docs}
    if not analysis or not structured.get("cv") or not structured.get("jd"):
        raise AppError(
            "not_analyzed", "Run the CV and job analysis before the interview.", status_code=409
        )
    gaps = [GapItem.model_validate(g) for g in analysis[0]["gaps"]]
    return (
        CVProfile.model_validate(structured["cv"]),
        JobProfile.model_validate(structured["jd"]),
        gaps,
    )


# ------------------------------------------------------------------ persistence


def _question_row(session_id: str, q: Any, parent_id: str | None) -> dict[str, Any]:
    return {
        "id": q.id,
        "session_id": session_id,
        "order_index": q.order,
        "type": q.type,
        "competency": q.competency,
        "text": q.text,
        "parent_question_id": parent_id,
        "rubric_chunk_ids": list(getattr(q, "rubric_chunk_ids", [])),
    }


class TurnConflictError(AppError):
    """Another request committed a turn for this interview first (double submit, two tabs)."""

    def __init__(self) -> None:
        super().__init__(
            "turn_conflict",
            "This question was already answered (maybe in another tab). Reload to continue.",
            status_code=409,
        )


async def persist(
    db: SupabaseRest, before: "InterviewState | None", after: "InterviewState"
) -> None:
    """Write the turn's rows, then the state (the state is the commit point).

    Writes run in parallel where foreign keys allow it: an answer always belongs to a question
    inserted by an EARLIER request, so new questions and the answer can go together.

    The state write is a compare-and-swap: a first turn is a plain INSERT (the primary key
    rejects a parallel start), later turns only update the row while it still waits for the
    question this turn answered. The loser removes its own rows and raises TurnConflictError,
    so two parallel submits of one answer can't both be recorded (security re-audit S2-2).
    """
    sid = after.session_id
    rows = [_question_row(sid, q, None) for q in after.new_planned]
    rows += [_question_row(sid, q, q.parent_id) for q in after.new_questions]
    answer_rows = []
    if after.new_answer:
        a = after.new_answer
        answer_rows.append(
            {
                "id": a.id,
                "question_id": a.question_id,
                "transcript": a.transcript,
                "duration_seconds": a.duration_seconds,
                # Phase 4 voice metrics (null for text answers)
                "words_per_minute": a.words_per_minute,
                "filler_count": a.filler_count,
                "filler_breakdown": a.filler_breakdown,
                "long_pauses": a.long_pauses,
                "scores": a.scores.model_dump(),
                "feedback": a.feedback.model_dump(),
            }
        )
    await asyncio.gather(db.insert("questions", rows), db.insert("answers", answer_rows))
    saved = after.clear_transient()
    values = {"state": saved.model_dump(mode="json"), "updated_at": datetime.now(UTC).isoformat()}
    if not await _commit_state(db, sid, before, values):
        await _discard(db, [str(r["id"]) for r in rows], [str(r["id"]) for r in answer_rows])
        log.warning("interview_turn_conflict", extra={"extra_fields": {"session_id": sid}})
        raise TurnConflictError()
    if before is None or before.status != after.status:
        status = "completed" if after.status == "completed" else "interviewing"
        await db.update("sessions", {"id": f"eq.{sid}"}, {"status": status})


async def _commit_state(
    db: SupabaseRest, sid: str, before: "InterviewState | None", values: dict[str, Any]
) -> bool:
    if before is None:
        try:
            await db.insert("interview_state", [{"session_id": sid, **values}])
        except DatabaseError as exc:
            if exc.status_code == 409:  # unique violation: a parallel start committed first
                return False
            raise
        return True
    params = {"session_id": f"eq.{sid}"}
    if before.current is not None:
        params["state->current->>id"] = f"eq.{before.current.id}"
    changed = await db.update_returning("interview_state", params, values, select="session_id")
    return bool(changed)


async def _discard(db: SupabaseRest, question_ids: list[str], answer_ids: list[str]) -> None:
    """Best effort: remove the rows a losing turn inserted (answers first: they reference
    questions). Leftovers are harmless: the state is the source of truth and nothing reads
    rows it does not point to."""
    try:
        if answer_ids:
            await db.delete("answers", {"id": f"in.({','.join(answer_ids)})"})
        if question_ids:
            await db.delete("questions", {"id": f"in.({','.join(question_ids)})"})
    except DatabaseError:
        log.warning("interview_conflict_cleanup_failed")


# ------------------------------------------------------------------ response


def question_out(q: "AskedQuestion") -> QuestionOut:
    return QuestionOut(
        id=q.id,
        order=q.order,
        type=q.type,
        competency=q.competency,
        text=q.text,
        is_follow_up=q.is_follow_up,
    )


def to_turn(state: "InterviewState", *, history: bool, last_answer: bool) -> InterviewTurn:
    last = None
    if last_answer and state.history:
        t = state.history[-1]
        feedback = (
            FeedbackOut(summary=t.feedback.summary, tip=t.feedback.tip)
            if state.practice_mode and t.feedback
            else None
        )
        last = LastAnswer(question_id=t.question.id, transcript=t.answer_text, feedback=feedback)
    return InterviewTurn(
        status="completed" if state.status == "completed" else "interviewing",
        practice_mode=state.practice_mode,
        progress=Progress(answered=state.answered_main(), total_planned=len(state.plan)),
        question=question_out(state.current) if state.current else None,
        last_answer=last,
        history=[
            HistoryItem(question=question_out(t.question), answer_text=t.answer_text)
            for t in state.history
        ]
        if history
        else [],
    )


# ------------------------------------------------------------------ use cases


Inputs = tuple[CVProfile, JobProfile, list[GapItem]]
# Called once the request is known to need an LLM turn (after validation, before the LLM call):
# the router uses it for rate limits and per-session quotas, so rejected requests cost nothing.
Charge = Callable[[], Awaitable[None]]


async def _free() -> None:
    return None


async def _run(
    db: SupabaseRest,
    llm: LLMClient,
    embedder: Embedder,
    state: "InterviewState",
    session_id: UUID,
    inputs: Inputs,
) -> "InterviewState":
    from app.agents.interviewer.graph import run_turn
    from app.agents.interviewer.state import InterviewContext

    cv, job, gaps = inputs
    ctx = InterviewContext(
        llm=llm, retriever=Retriever(db, embedder), db=db, cv=cv, job=job, gaps=gaps
    )
    started = time.perf_counter()
    try:
        result = await run_turn(state, ctx)
    except LLMError as exc:
        log.warning("interview_llm_failed", extra={"extra_fields": {"session_id": str(session_id)}})
        raise ai_unavailable() from exc
    log.info(
        "interview_turn",
        extra={
            "extra_fields": {
                "session_id": str(session_id),
                "event": state.event,
                "route": result.route,
                "status": result.status,
                "graph_ms": round((time.perf_counter() - started) * 1000),
            }
        },
    )
    return result


async def start_interview(
    db: SupabaseRest,
    llm: LLMClient,
    embedder: Embedder,
    session: dict[str, Any],
    practice_mode: bool,
    charge: Charge = _free,
) -> InterviewTurn:
    from app.agents.interviewer.state import InterviewState

    sid = UUID(session["id"])
    existing = await load_state(db, sid)
    if existing is not None:  # idempotent: never re-plan (and never charged twice)
        return to_turn(existing, history=False, last_answer=False)
    inputs = await load_inputs(db, sid)
    await charge()
    state = InterviewState(
        session_id=str(sid),
        practice_mode=practice_mode,
        difficulty=session.get("difficulty") or "junior",
        interview_type=session.get("interview_type") or "mixed",
        event="start",
    )
    result = await _run(db, llm, embedder, state, sid, inputs)
    try:
        await persist(db, None, result)
    except TurnConflictError:
        # A parallel start (double click, second tab) planned first: keep start idempotent.
        existing = await load_state(db, sid)
        if existing is None:
            raise
        return to_turn(existing, history=False, last_answer=False)
    return to_turn(result, history=False, last_answer=False)


async def get_interview(db: SupabaseRest, session: dict[str, Any]) -> InterviewTurn:
    state = await load_state(db, UUID(session["id"]))
    if state is None:
        raise _not_started()
    return to_turn(state, history=True, last_answer=True)


async def submit_answer(
    db: SupabaseRest,
    llm: LLMClient,
    embedder: Embedder,
    session: dict[str, Any],
    question_id: UUID,
    transcript: str,
    charge: Charge = _free,
    speech: SpeechMetrics | None = None,
) -> InterviewTurn:
    """Text answers, and voice answers after transcription (`speech` = their metrics)."""
    sid = UUID(session["id"])
    transcript = transcript.strip()
    if not transcript:
        raise AppError("validation_error", "The answer cannot be empty.", status_code=422)
    # Load state and profiles together (one round trip less per answer). The state is checked
    # first so a missing interview reports `not_started`, not `not_analyzed`.
    loaded_state, loaded_inputs = await asyncio.gather(
        load_state(db, sid), load_inputs(db, sid), return_exceptions=True
    )
    if isinstance(loaded_state, BaseException):
        raise loaded_state
    state = _check_answerable(loaded_state, question_id)
    if isinstance(loaded_inputs, BaseException):
        raise loaded_inputs
    await charge()
    turn_input = state.model_copy(update={"event": "answer", "answer_text": transcript})
    result = await _run(db, llm, embedder, turn_input, sid, loaded_inputs)
    if speech is not None:
        result = with_speech_metrics(result, speech)
    await persist(db, state, result)
    turn = to_turn(result, history=False, last_answer=True)
    if speech is not None and turn.last_answer is not None:
        turn.last_answer.speech_metrics = speech
    return turn


def with_speech_metrics(state: "InterviewState", m: SpeechMetrics) -> "InterviewState":
    """Attach a voice answer's metrics to the `answers` row this turn writes."""
    if state.new_answer is None:
        return state
    row = state.new_answer.model_copy(
        update={
            "duration_seconds": m.duration_seconds,
            "words_per_minute": m.words_per_minute,
            "filler_count": m.filler_count,
            "filler_breakdown": m.filler_breakdown,
            "long_pauses": m.long_pauses,
        }
    )
    return state.model_copy(update={"new_answer": row})


def _not_started() -> AppError:
    return AppError("not_started", "The interview has not been started yet.", status_code=409)


def _check_answerable(state: "InterviewState | None", question_id: UUID) -> "InterviewState":
    if state is None:
        raise _not_started()
    if state.status == "completed" or state.current is None:
        raise AppError(
            "interview_completed", "This interview is already finished.", status_code=409
        )
    if state.current.id != str(question_id):
        raise AppError(
            "wrong_question",
            "That question is not the one waiting for an answer. Reload to continue.",
            status_code=400,
        )
    return state
