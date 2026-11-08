"""The agent's tools: search_cv, search_rubric, score_answer.

They are plain async functions (not LLM tool-calls): the graph decides WHEN to call them, so the
number of LLM calls per turn is fixed and predictable (important on a free-tier token budget).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.agents.interviewer.prompts import EVAL_SYSTEM
from app.agents.interviewer.state import AskedQuestion, RubricSnippet
from app.db.client import SupabaseRest
from app.schemas.analysis import CVProfile
from app.schemas.interview import (
    AnswerEvaluationDraft,
    AnswerFeedback,
    AnswerQuality,
    AnswerScores,
    CriterionDraft,
    CriterionScore,
)
from app.services.evidence import normalize, quote_in_text
from app.services.llm import LLMClient, wrap_untrusted
from app.services.retrieval import Level, RetrievedChunk, Retriever

RUBRIC_SNIPPET_CHARS = 700
MAX_TRANSCRIPT_CHARS_FOR_LLM = 5000
NON_TECHNICAL_TYPES = {"behavioral", "role_fit"}
ANCHOR_MARKER = "Scoring anchors"


async def search_cv(
    retriever: Retriever, session_id: UUID, queries: list[str], k: int = 2
) -> list[list[RetrievedChunk]]:
    """Hybrid search over THIS session's CV chunks (one batched embedding call)."""
    return await retriever.search_cv_many(session_id, queries, k=k)


async def search_rubric(
    retriever: Retriever,
    queries: Sequence[tuple[str, str | None]],
    level: Level,
    k: int = 2,
) -> list[list[RetrievedChunk]]:
    """Hybrid search over the rubric knowledge base, per (query, competency)."""
    return await retriever.search_rubric_many(queries, level=level, k=k)


async def scoring_anchors(
    db: SupabaseRest, competencies: set[str]
) -> dict[str, list[RubricSnippet]]:
    """The 1/3/5 anchor chunks per competency (deterministic lookup, no embedding needed)."""
    if not competencies:
        return {}
    rows = await db.select(
        "knowledge_chunks",
        {
            "select": "id,competency,content,chunk_index",
            "competency": f"in.({','.join(sorted(competencies))})",
            "content": f"like.*{ANCHOR_MARKER}*",
            "order": "chunk_index.asc",
        },
    )
    out: dict[str, list[RubricSnippet]] = {}
    for r in rows:
        out.setdefault(r["competency"], []).append(
            RubricSnippet(id=str(r["id"]), content=r["content"][:RUBRIC_SNIPPET_CHARS])
        )
    return out


def snippet(chunk: RetrievedChunk) -> RubricSnippet:
    return RubricSnippet(id=str(chunk.id), content=chunk.content[:RUBRIC_SNIPPET_CHARS])


def cv_facts(cv: CVProfile) -> str:
    """A compact CV summary (~100-300 tokens) so the improved answer stays honest."""
    facts = {
        "skills": cv.skills[:15],
        "projects": [
            {"title": p.title, "stack": p.stack[:6], "outcome": p.outcome} for p in cv.projects[:4]
        ],
        "experience": [f"{e.role} at {e.org}" for e in cv.experience[:3]],
    }
    return json.dumps(facts, ensure_ascii=False)


@dataclass(frozen=True)
class ScoredAnswer:
    scores: AnswerScores
    feedback: AnswerFeedback
    quality: AnswerQuality
    follow_up_question: str | None
    transition: str


def _criterion(draft: CriterionDraft, normalized_transcript: str) -> CriterionScore:
    verified = quote_in_text(draft.evidence_quote, normalized_transcript)
    return CriterionScore(
        score=int(draft.score),  # "1".."5" enforced by the schema; int() can't fail
        justification=draft.justification[:400],
        evidence_quote=draft.evidence_quote[:300] if verified and draft.evidence_quote else None,
        quote_verified=verified,
    )


def to_scores(draft: AnswerEvaluationDraft, transcript: str, question_type: str) -> AnswerScores:
    """Validated LLM draft -> stored scores. Quotes must exist in the transcript."""
    norm = normalize(transcript)
    tech = (
        None
        if question_type in NON_TECHNICAL_TYPES or draft.technical_accuracy is None
        else _criterion(draft.technical_accuracy, norm)
    )
    parts = {
        "relevance": _criterion(draft.relevance, norm),
        "depth": _criterion(draft.depth, norm),
        "structure": _criterion(draft.structure, norm),
        "communication": _criterion(draft.communication, norm),
    }
    values = [c.score for c in parts.values()] + ([tech.score] if tech else [])
    return AnswerScores(
        technical_accuracy=tech, average=round(sum(values) / len(values), 2), **parts
    )


async def score_answer(
    llm: LLMClient,
    question: AskedQuestion,
    answer: str,
    rubric: list[RubricSnippet],
    *,
    cv: CVProfile,
    level: str,
    parent: tuple[str, str] | None = None,
    probe_hint: str | None = None,
) -> ScoredAnswer:
    """ONE fast-model call: score (SPEC 6.5) + follow-up decision signal + follow-up phrasing."""
    # Calibration: ALL the 1/3/5 anchors + the single most relevant question-bank chunk.
    anchors = [r for r in rubric if ANCHOR_MARKER in r.content.split("\n", 1)[0]]
    bank = [r for r in rubric if r not in anchors][:1]
    picked = bank + anchors[:4]
    rubric_text = "\n\n".join(f"[R{i + 1}] {r.content}" for i, r in enumerate(picked))
    hint = f"IF SHALLOW, PROBE: {probe_hint}\n" if probe_hint and not parent else ""
    context = ""
    if parent:
        context = (
            "This is a FOLLOW-UP. Original question: "
            + parent[0]
            + "\n"
            + wrap_untrusted("transcript", parent[1][:800])
            + "\n\n"
        )
    user = (
        f"LEVEL: {level}\nQUESTION TYPE: {question.type}\nCOMPETENCY: {question.competency}\n"
        f"QUESTION: {question.text}\n{hint}\n"
        f"RUBRIC AND SCORING ANCHORS:\n{rubric_text or '(none)'}\n\n"
        f"CANDIDATE CV FACTS:\n{wrap_untrusted('cv', cv_facts(cv))}\n\n{context}"
        f"ANSWER TO SCORE:\n{wrap_untrusted('transcript', answer[:MAX_TRANSCRIPT_CHARS_FOR_LLM])}"
    )
    draft = await llm.structured(
        system=EVAL_SYSTEM,
        user=user,
        schema=AnswerEvaluationDraft,
        tier="fast",  # latency target < 4 s per answer; see docs/LEARNING.md Phase 3
        temperature=0.1,
        max_tokens=2000,
    )
    scores = to_scores(draft, answer, question.type)
    feedback = AnswerFeedback(
        summary=draft.feedback_summary[:400],
        tip=draft.one_tip[:400],
        what_interviewer_wanted=draft.what_interviewer_wanted[:600],
        improved_answer=draft.improved_answer[:1500],
    )
    follow = (draft.follow_up_question or "").strip()[:400] or None
    return ScoredAnswer(
        scores=scores,
        feedback=feedback,
        quality=draft.answer_quality,
        follow_up_question=follow,
        transition=draft.transition.strip()[:160],
    )
