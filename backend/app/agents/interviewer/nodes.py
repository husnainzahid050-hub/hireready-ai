"""Graph nodes. Each node takes the state and returns a PARTIAL update (a dict).

Nodes never write to the database: they put the rows to write in the per-request fields
(`new_planned`, `new_questions`, `new_answer`) and the service persists them after the run.
That keeps nodes pure and easy to test, and a failed LLM call leaves the database untouched.
"""

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langgraph.runtime import Runtime

from app.agents.interviewer.prompts import PLAN_SYSTEM
from app.agents.interviewer.state import (
    MAX_FOLLOW_UPS_PER_QUESTION,
    AskedQuestion,
    InterviewContext,
    InterviewState,
    NewAnswer,
    PlannedQuestion,
    RubricSnippet,
    Turn,
)
from app.agents.interviewer.tools import (
    score_answer,
    scoring_anchors,
    search_cv,
    search_rubric,
    snippet,
)
from app.schemas.analysis import CVProfile, GapItem, JobProfile
from app.schemas.interview import InterviewPlanDraft, MainQuestionType
from app.services.llm import wrap_untrusted

Ctx = Runtime[InterviewContext]

NON_TECH_COMPETENCIES = {"behavioral", "communication", "other"}
SLOT_ORDER: dict[str, list[MainQuestionType]] = {
    "mixed": ["technical", "technical", "project", "gap_probe", "behavioral", "role_fit"],
    "technical": ["technical", "technical", "technical", "project", "gap_probe", "role_fit"],
    "behavioral": ["behavioral", "behavioral", "behavioral", "project", "gap_probe", "role_fit"],
}
BEHAVIORAL_THEMES = {
    "junior": [
        "working in a team and handling a disagreement",
        "a mistake or failure and what you learned",
        "learning something new quickly",
    ],
    "mid": [
        "taking initiative beyond assigned work",
        "delivering under a tight deadline",
        "handling a disagreement with a colleague",
    ],
}
MIN_WORDS = 8  # answers shorter than this are always treated as shallow


# ------------------------------------------------------------------ slot selection (deterministic)


@dataclass
class Slot:
    type: MainQuestionType
    competency: str | None
    focus: str
    detail: str = ""  # extra facts for the planner (e.g. evidence verdict)


def _pick_project(cv: CVProfile, job: JobProfile) -> tuple[str, str, str | None] | None:
    """(title, detail, competency) of the CV project that best overlaps the JD must-haves."""
    must = {s.name.casefold(): s.competency for s in job.must_have_skills}
    best: tuple[int, int] | None = None
    for i, p in enumerate(cv.projects):
        overlap = sum(1 for t in p.stack if t.casefold() in must)
        if best is None or overlap > best[0]:
            best = (overlap, i)
    if best is not None:
        p = cv.projects[best[1]]
        comp = next((must[t.casefold()] for t in p.stack if t.casefold() in must), None)
        detail = f"stack: {', '.join(p.stack[:6])}; outcome: {p.outcome or 'not stated'}"
        return p.title, detail, comp
    if cv.experience:
        e = cv.experience[0]
        return f"{e.role} at {e.org}", "; ".join(e.bullets[:3]), None
    return None


def choose_slots(
    interview_type: str, difficulty: str, job: JobProfile, cv: CVProfile, gaps: list[GapItem]
) -> list[Slot]:
    """Decide WHAT each question is about, in code. The LLM only phrases them."""
    must = [g for g in gaps if g.importance == "must_have"]
    probe = next(
        (g for v in ("no_evidence", "weak_evidence") for g in must if g.verdict == v),
        next((g for g in gaps if g.verdict == "no_evidence"), None),
    )
    rank = {"strong_evidence": 0, "weak_evidence": 1, "no_evidence": 2}
    tech_pool = sorted(
        (g for g in must if g.competency not in NON_TECH_COMPETENCIES and g is not probe),
        key=lambda g: rank[g.verdict],
    )
    # Prefer distinct competencies, then allow repeats.
    distinct: list[GapItem] = []
    for g in tech_pool:
        if all(d.competency != g.competency for d in distinct):
            distinct.append(g)
    tech_queue = distinct + [g for g in tech_pool if g not in distinct]
    project = _pick_project(cv, job)
    themes = list(BEHAVIORAL_THEMES["mid" if difficulty == "mid" else "junior"])

    def technical() -> Slot:
        if tech_queue:
            g = tech_queue.pop(0)
            return Slot("technical", g.competency, g.skill, f"CV evidence: {g.verdict}")
        return Slot("technical", "problem_solving", "problem solving and debugging approach")

    def behavioral() -> Slot:
        theme = themes.pop(0) if themes else "a challenge you are proud of overcoming"
        return Slot("behavioral", "behavioral", theme)

    slots: list[Slot] = []
    for kind in SLOT_ORDER.get(interview_type, SLOT_ORDER["mixed"]):
        if kind == "technical":
            slots.append(technical())
        elif kind == "behavioral":
            slots.append(behavioral())
        elif kind == "project":
            if project:
                title, detail, comp = project
                slots.append(Slot("project", comp or "problem_solving", title, detail))
            else:
                slots.append(behavioral() if interview_type == "behavioral" else technical())
        elif kind == "gap_probe":
            if probe:
                slots.append(
                    Slot(
                        "gap_probe", probe.competency, probe.skill, f"CV evidence: {probe.verdict}"
                    )
                )
            else:
                slots.append(behavioral() if interview_type == "behavioral" else technical())
        else:
            slots.append(
                Slot(
                    "role_fit",
                    "communication",
                    job.title or "this role",
                    "motivation for this role and how they would add value (not a technical or "
                    "explain-it-simply question)",
                )
            )
    return slots


def _fallback_question(slot: Slot, role: str) -> tuple[str, str]:
    """Template phrasing if the planner returned too few questions."""
    text = {
        "technical": f"How have you used {slot.focus}, and what would you watch out for when "
        f"using it in a role like {role}?",
        "project": f"Could you walk me through {slot.focus}: what you built, the key decisions "
        "you made, and the result?",
        "gap_probe": f"This role uses {slot.focus}. What do you know about it so far, and how "
        "would you get up to speed?",
        "behavioral": f"Tell me about a specific time involving {slot.focus}. What was the "
        "situation, what did you do, and what was the result?",
        "role_fit": f"What attracts you to the {role} role, and how would you add value in your "
        "first few months?",
    }[slot.type]
    return text, "Ask for a concrete example with specific details."


def _bank_titles(chunks: list[Any]) -> list[str]:
    """Question-bank chunk heading -> the example question it holds."""
    out = []
    for c in chunks:
        head = c.content.splitlines()[0]
        if "Question bank" in head:
            out.append(head.split(" > ")[-1])
    return out[:2]


# ------------------------------------------------------------------ nodes


async def plan_interview(state: InterviewState, runtime: Ctx) -> dict[str, Any]:
    """ONE LLM call phrases all questions; rubric chunks are fetched once and kept in the state."""
    ctx = runtime.context
    level = "mid" if state.difficulty == "mid" else "junior"
    slots = choose_slots(state.interview_type, level, ctx.job, ctx.cv, ctx.gaps)

    rubric_hits, anchors, cv_hits = await asyncio.gather(
        search_rubric(
            ctx.retriever,
            [(f"{s.focus} {s.competency or ''} interview question", s.competency) for s in slots],
            level,  # type: ignore[arg-type]
            k=2,
        ),
        scoring_anchors(ctx.db, {s.competency for s in slots if s.competency}),
        search_cv(
            ctx.retriever,
            UUID(state.session_id),
            [s.focus for s in slots if s.type == "project"] or [""],
            k=2,
        ),
    )
    cv_excerpts = [c.content[:500] for chunks in cv_hits for c in chunks][:2]

    slot_specs = [
        {
            "slot": i + 1,
            "type": s.type,
            "competency": s.competency,
            "about": s.focus,
            "notes": s.detail,
            "example_questions": [] if s.type == "role_fit" else _bank_titles(hits),
        }
        for i, (s, hits) in enumerate(zip(slots, rubric_hits, strict=True))
    ]
    job = {
        "title": ctx.job.title,
        "seniority": ctx.job.seniority,
        "responsibilities": ctx.job.responsibilities[:4],
    }
    candidate = {"name": ctx.cv.name, "project_excerpts": cv_excerpts}
    user = (
        f"DIFFICULTY: {level}\nSLOTS:\n{json.dumps(slot_specs, ensure_ascii=False)}\n\n"
        f"JOB:\n{json.dumps(job, ensure_ascii=False)}\n\n"
        f"CANDIDATE (untrusted CV data):\n"
        f"{wrap_untrusted('cv', json.dumps(candidate, ensure_ascii=False))}"
    )
    draft = await ctx.llm.structured(
        system=PLAN_SYSTEM,
        user=user,
        schema=InterviewPlanDraft,
        tier="strong",
        temperature=0.4,
        max_tokens=2000,
    )

    plan: list[PlannedQuestion] = []
    for i, (s, hits) in enumerate(zip(slots, rubric_hits, strict=True)):
        if i < len(draft.questions) and draft.questions[i].text.strip():
            text, hint = draft.questions[i].text.strip(), draft.questions[i].follow_up_hint.strip()
        else:
            text, hint = _fallback_question(s, ctx.job.title or "this")
        rubric = [snippet(c) for c in hits] + anchors.get(s.competency or "", [])
        plan.append(
            PlannedQuestion(
                id=str(uuid.uuid4()),
                order=i + 1,
                type=s.type,
                competency=s.competency,
                focus=s.focus,
                text=text[:600],
                follow_up_hint=hint[:300],
                rubric=_dedupe(rubric),
            )
        )
    return {
        "plan": plan,
        "new_planned": plan,
        "plan_index": 0,
        "status": "interviewing",
        "transition": draft.opening.strip()[:300],
    }


def _dedupe(rubric: list[RubricSnippet]) -> list[RubricSnippet]:
    return list({r.id: r for r in rubric}.values())


async def ask_question(state: InterviewState) -> dict[str, Any]:
    """Put the next planned question to the candidate (with a short natural lead-in)."""
    q = state.plan[state.plan_index]
    lead = (state.transition or "").strip()
    text = f"{lead} {q.text}".strip() if lead else q.text
    asked = AskedQuestion(
        id=q.id,
        order=q.order,
        type=q.type,
        competency=q.competency,
        text=text,
        is_follow_up=False,
        parent_id=None,
    )
    return {"current": asked}


def _main_question(state: InterviewState, asked: AskedQuestion) -> PlannedQuestion:
    main_id = asked.parent_id or asked.id
    return next(p for p in state.plan if p.id == main_id)


async def evaluate_answer(state: InterviewState, runtime: Ctx) -> dict[str, Any]:
    """Score the answer against the question's prefetched rubric + anchors (one LLM call)."""
    ctx = runtime.context
    asked = state.current
    assert asked is not None and state.answer_text is not None  # noqa: S101 (checked by service)
    main = _main_question(state, asked)
    parent = None
    if asked.is_follow_up:
        prev = next((t for t in reversed(state.history) if t.question.id == main.id), None)
        parent = (main.text, prev.answer_text if prev else "")
    result = await score_answer(
        ctx.llm,
        asked,
        state.answer_text,
        main.rubric,
        cv=ctx.cv,
        level=state.difficulty,
        parent=parent,
        probe_hint=main.follow_up_hint,
    )
    answer = NewAnswer(
        id=str(uuid.uuid4()),
        question_id=asked.id,
        transcript=state.answer_text,
        scores=result.scores,
        feedback=result.feedback,
    )
    turn = Turn(
        question=asked,
        answer_id=answer.id,
        answer_text=state.answer_text,
        scores=result.scores,
        feedback=result.feedback,
    )
    return {
        "history": [*state.history, turn],
        "new_answer": answer,
        "answer_quality": result.quality,
        "follow_up_text": result.follow_up_question,
        "transition": result.transition,
    }


_WORD = re.compile(r"\w+")


def is_shallow(state: InterviewState) -> bool:
    words = len(_WORD.findall(state.answer_text or ""))
    depth = state.history[-1].scores.depth.score if state.history[-1].scores else 3
    return state.answer_quality != "complete" or words < MIN_WORDS or depth <= 1


async def decide_next(state: InterviewState) -> dict[str, Any]:
    """Follow-up if shallow and no follow-up yet for this question; else next; else finish."""
    asked = state.current
    assert asked is not None  # noqa: S101
    main_id = asked.parent_id or asked.id
    asked_follow_ups = state.follow_up_counts.get(main_id, 0)
    if (
        not asked.is_follow_up
        and asked_follow_ups < MAX_FOLLOW_UPS_PER_QUESTION
        and is_shallow(state)
    ):
        return {"route": "follow_up"}
    if state.plan_index + 1 < len(state.plan):
        return {"route": "next", "plan_index": state.plan_index + 1}
    return {"route": "finish"}


def route_after_decide(state: InterviewState) -> str:
    return {"follow_up": "ask_follow_up", "next": "ask_question"}.get(state.route or "", "finish")


async def ask_follow_up(state: InterviewState) -> dict[str, Any]:
    """A targeted follow-up. Its text comes from the evaluation call (it saw the transcript)."""
    asked = state.current
    assert asked is not None  # noqa: S101
    main = _main_question(state, asked)
    text = state.follow_up_text or (
        # The plan's follow_up_hint is an interviewer-facing note: never shown verbatim.
        "Could you go a bit deeper on that, with a specific example from your own experience?"
    )
    follow = AskedQuestion(
        id=str(uuid.uuid4()),
        order=main.order,
        type="follow_up",
        competency=main.competency,
        text=text.strip(),
        is_follow_up=True,
        parent_id=main.id,
    )
    counts = dict(state.follow_up_counts)
    counts[main.id] = counts.get(main.id, 0) + 1
    return {"current": follow, "new_questions": [follow], "follow_up_counts": counts}


async def finish(state: InterviewState) -> dict[str, Any]:
    """Mark the interview complete; the report (Phase 5) is generated from the stored answers."""
    return {"status": "completed", "current": None, "report_pending": True}


def route_entry(state: InterviewState) -> str:
    return "plan_interview" if state.event == "start" else "evaluate_answer"
