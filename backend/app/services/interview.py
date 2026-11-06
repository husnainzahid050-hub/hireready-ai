"""Interview service: load state -> run ONE graph turn -> persist -> build the API response.

Serverless-friendly: nothing is kept in memory between requests. The full graph state is a JSON
document in `interview_state`; questions and answers also go to their own tables (used by the
Phase 5 report). LangGraph is imported lazily so other endpoints don't pay its import time.
"""

import asyncio
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.errors import AppError, ai_unavailable
from app.core.logging import get_logger
from app.db.client import SupabaseRest
from app.schemas.analysis import CVProfile, GapItem, JobProfile
from app.schemas.interview import (
    FeedbackOut,
    HistoryItem,
    InterviewTurn,
    LastAnswer,
    Progress,
    QuestionOut,
)
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


async def persist(
    db: SupabaseRest, before: "InterviewState | None", after: "InterviewState"
) -> None:
    """Write the turn's rows, then the state (the state is the commit point).

    Writes run in parallel where foreign keys allow it: an answer always belongs to a question
    inserted by an EARLIER request, so new questions and the answer can go together.
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
                "scores": a.scores.model_dump(),
                "feedback": a.feedback.model_dump(),
            }
        )
    await asyncio.gather(db.insert("questions", rows), db.insert("answers", answer_rows))
    saved = after.clear_transient()
    writes = [
        db.insert(
            "interview_state",
            [
                {
                    "session_id": sid,
                    "state": saved.model_dump(mode="json"),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ],
            on_conflict="session_id",
        )
    ]
    if before is None or before.status != after.status:
        status = "completed" if after.status == "completed" else "interviewing"
        writes.append(db.update("sessions", {"id": f"eq.{sid}"}, {"status": status}))
    await asyncio.gather(*writes)


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
) -> InterviewTurn:
    from app.agents.interviewer.state import InterviewState

    sid = UUID(session["id"])
    existing = await load_state(db, sid)
    if existing is not None:  # idempotent: never re-plan
        return to_turn(existing, history=False, last_answer=False)
    state = InterviewState(
        session_id=str(sid),
        practice_mode=practice_mode,
        difficulty=session.get("difficulty") or "junior",
        interview_type=session.get("interview_type") or "mixed",
        event="start",
    )
    result = await _run(db, llm, embedder, state, sid, await load_inputs(db, sid))
    await persist(db, None, result)
    return to_turn(result, history=False, last_answer=False)


async def get_interview(db: SupabaseRest, session: dict[str, Any]) -> InterviewTurn:
    state = await load_state(db, UUID(session["id"]))
    if state is None:
        raise AppError("not_started", "The interview has not been started yet.", status_code=409)
    return to_turn(state, history=True, last_answer=True)


async def submit_answer(
    db: SupabaseRest,
    llm: LLMClient,
    embedder: Embedder,
    session: dict[str, Any],
    question_id: UUID,
    transcript: str,
) -> InterviewTurn:
    """Text answers now; Phase 4 voice will transcribe audio and call this same function."""
    sid = UUID(session["id"])
    transcript = transcript.strip()
    if not transcript:
        raise AppError("validation_error", "The answer cannot be empty.", status_code=422)
    # Load the profiles while we validate the state: saves a database round trip per answer.
    inputs_task = asyncio.create_task(load_inputs(db, sid))
    try:
        state = await load_state(db, sid)
        _check_answerable(state, question_id)
        inputs = await inputs_task
    finally:
        if not inputs_task.done():
            inputs_task.cancel()
        elif not inputs_task.cancelled():
            inputs_task.exception()  # mark a failure as retrieved (we raised our own error)
    assert state is not None  # noqa: S101 (checked above)
    turn_input = state.model_copy(update={"event": "answer", "answer_text": transcript})
    result = await _run(db, llm, embedder, turn_input, sid, inputs)
    await persist(db, state, result)
    return to_turn(result, history=False, last_answer=True)


def _check_answerable(state: "InterviewState | None", question_id: UUID) -> None:
    if state is None:
        raise AppError("not_started", "The interview has not been started yet.", status_code=409)
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
