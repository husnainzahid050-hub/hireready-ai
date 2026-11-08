"""Gap-analysis pipeline. Yields (event, payload) pairs so the router can stream them (SSE).

Steps:
 1. Extract CV + JD profiles in parallel (LLM, fast model). JD extraction cached by content hash.
 2. Chunk + embed the CV into doc_chunks (once per CV).
 3. For every JD skill, retrieve the best CV excerpts (hybrid search, one batched embedding call).
 4. LLM judges evidence per skill; each quote is verified against the CV text (anti-hallucination).
 5. Deterministic match score.
 6. LLM writes strengths, likely questions (adapted from the rubric KB) and a 7-day plan that may
    only use curated resource URLs.

Only one run per session at a time: the router claims the session first (`claim_run`, an atomic
SQL function), and a second caller waits for the first run's result instead (`wait_for_run`).
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.client import SupabaseRest
from app.db.repositories import cached_jd_structure, get_documents
from app.schemas.analysis import (
    Analysis,
    CVProfile,
    EvidenceJudgements,
    GapItem,
    Insights,
    InsightsDraft,
    JobProfile,
    JobSkill,
    PrepDay,
)
from app.services.catalog import allowed_urls, resources_for
from app.services.embeddings import Embedder, to_pgvector
from app.services.evidence import normalize, quote_in_text, validate_judgement
from app.services.llm import LLMClient, wrap_untrusted
from app.services.parsing import chunk_cv
from app.services.prompts import CV_SYSTEM, INSIGHTS_SYSTEM, JD_SYSTEM, JUDGE_SYSTEM
from app.services.retrieval import Retriever, rubric_level
from app.services.scoring import compute_match

log = get_logger(__name__)

MAX_CV_CHARS_FOR_LLM = 12_000  # ~3k tokens: stays inside free-tier per-minute token budgets
MAX_MUST, MAX_NICE = 12, 8

# A claim older than this is treated as abandoned (crashed or killed function). Vercel stops the
# function after 60 s (backend/vercel.json), so a live run can never be this old.
CLAIM_TTL_S = 120
# A second caller polls for the first run's result for at most this long (inside the 60 s limit).
WAIT_POLL_S = 2.0
WAIT_TIMEOUT_S = 45.0

Event = tuple[str, dict[str, Any]]


# ------------------------------------------------------------------ one run per session


async def saved_analysis(db: SupabaseRest, session_id: UUID) -> "Analysis | None":
    rows = await db.select("gap_analyses", {"select": "*", "session_id": f"eq.{session_id}"})
    return analysis_from_row(rows[0]) if rows else None


async def claim_run(db: SupabaseRest, session_id: UUID) -> bool:
    """True if this request now owns the session's analysis run (see migration 05)."""
    claimed = await db.rpc(
        "claim_analysis", {"p_session_id": str(session_id), "p_stale_seconds": CLAIM_TTL_S}
    )
    return claimed is True


async def release_run(db: SupabaseRest, session_id: UUID) -> None:
    await db.update("sessions", {"id": f"eq.{session_id}"}, {"analysis_started_at": None})


async def wait_for_run(db: SupabaseRest, session_id: UUID) -> AsyncIterator[Event]:
    """Another request is analyzing this session: stream its result once it is saved."""
    yield (
        "status",
        {
            "step": "waiting",
            "message": "This analysis is already running (maybe in another tab). "
            "Waiting for it to finish…",
        },
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_TIMEOUT_S
    while True:
        # Claim first, then result: a run saves its result BEFORE it releases the claim.
        rows = await db.select(
            "sessions", {"select": "analysis_started_at", "id": f"eq.{session_id}"}
        )
        running = bool(rows and rows[0].get("analysis_started_at"))
        saved = await saved_analysis(db, session_id)
        if saved:
            yield "done", saved.model_dump()
            return
        if not running:
            raise AppError(
                "analysis_interrupted",
                "The other analysis run stopped before finishing. Please try again.",
            )
        if loop.time() >= deadline:
            raise AppError(
                "analysis_in_progress",
                "Your analysis is still running. Reload this page in a moment to see it.",
            )
        await asyncio.sleep(WAIT_POLL_S)


# ------------------------------------------------------------------ pipeline steps


async def extract_profiles(
    db: SupabaseRest, llm: LLMClient, docs: dict[str, dict[str, Any]]
) -> tuple[CVProfile, JobProfile]:
    cv_doc, jd_doc = docs["cv"], docs["jd"]

    async def cv_task() -> CVProfile:
        if cv_doc.get("structured"):
            return CVProfile.model_validate(cv_doc["structured"])
        return await llm.structured(
            system=CV_SYSTEM,
            user=wrap_untrusted("cv", cv_doc["raw_text"][:MAX_CV_CHARS_FOR_LLM]),
            schema=CVProfile,
            tier="fast",
            max_tokens=6000,
        )

    async def jd_task() -> JobProfile:
        if jd_doc.get("structured"):
            return JobProfile.model_validate(jd_doc["structured"])
        cached = await cached_jd_structure(db, jd_doc["content_hash"])
        if cached:
            return JobProfile.model_validate(cached)
        return await llm.structured(
            system=JD_SYSTEM,
            user=wrap_untrusted("jd", jd_doc["raw_text"]),
            schema=JobProfile,
            tier="fast",
            max_tokens=2000,
        )

    cv, job = await asyncio.gather(cv_task(), jd_task())
    job = job.model_copy(
        update={
            "must_have_skills": job.must_have_skills[:MAX_MUST],
            "nice_to_have_skills": job.nice_to_have_skills[:MAX_NICE],
        }
    )
    await asyncio.gather(
        db.update("documents", {"id": f"eq.{cv_doc['id']}"}, {"structured": cv.model_dump()}),
        db.update("documents", {"id": f"eq.{jd_doc['id']}"}, {"structured": job.model_dump()}),
    )
    return cv, job


async def index_cv(db: SupabaseRest, embedder: Embedder, cv_doc: dict[str, Any]) -> int:
    existing = await db.select(
        "doc_chunks", {"select": "id", "document_id": f"eq.{cv_doc['id']}", "limit": "1"}
    )
    if existing:
        return 0
    pieces = chunk_cv(cv_doc["raw_text"])
    vectors = await embedder.embed(pieces, "RETRIEVAL_DOCUMENT")
    await db.insert(
        "doc_chunks",
        [
            {
                "document_id": cv_doc["id"],
                "chunk_index": i,
                "content": text,
                "embedding": to_pgvector(v),
                "metadata": {},
            }
            for i, (text, v) in enumerate(zip(pieces, vectors, strict=True))
        ],
    )
    return len(pieces)


async def judge_skills(
    llm: LLMClient,
    retriever: Retriever,
    session_id: UUID,
    skills: list[tuple[JobSkill, str]],
    cv_text: str,
) -> list[GapItem]:
    if not skills:
        return []
    evidence = await retriever.search_cv_many(session_id, [s.name for s, _ in skills], k=3)
    # Each CV excerpt is sent ONCE with an id; skills only reference ids. Without this the same
    # excerpts repeat for every skill (~7k tokens), blowing the free-tier tokens-per-minute budget.
    excerpt_ids: dict[str, str] = {}
    contents: dict[str, str] = {}
    for chunks in evidence:
        for c in chunks:
            excerpt_ids.setdefault(str(c.id), f"E{len(excerpt_ids) + 1}")
            contents[str(c.id)] = c.content
    excerpt_text = "\n\n".join(f"[{eid}]\n{contents[cid]}" for cid, eid in excerpt_ids.items())
    skill_lines = [
        f"- {skill.name}: check "
        + (", ".join(excerpt_ids[str(c.id)] for c in chunks) or "(no excerpts found)")
        for (skill, _), chunks in zip(skills, evidence, strict=True)
    ]
    result = await llm.structured(
        system=JUDGE_SYSTEM,
        user=wrap_untrusted("evidence", excerpt_text or "(no excerpts)")
        + "\n\nSKILLS TO JUDGE:\n"
        + "\n".join(skill_lines),
        schema=EvidenceJudgements,
        tier="strong",
        temperature=0.0,  # judging should be as repeatable as possible
        max_tokens=5000,
    )
    by_name = {normalize(j.skill): j for j in result.judgements}
    normalized_cv = normalize(cv_text)
    gaps: list[GapItem] = []
    for skill, importance in skills:
        verdict, quote, reason, verified = validate_judgement(
            by_name.get(normalize(skill.name)), skill, normalized_cv
        )
        gaps.append(
            GapItem(
                skill=skill.name,
                importance=importance,
                competency=skill.competency,
                verdict=verdict,
                evidence_quote=quote,
                reason=reason,
                quote_verified=verified,
            )
        )
    return gaps


async def build_insights(
    llm: LLMClient,
    retriever: Retriever,
    cv: CVProfile,
    job: JobProfile,
    gaps: list[GapItem],
    difficulty: str,
    cv_text: str,
) -> Insights:
    competencies = list(dict.fromkeys(g.competency for g in gaps if g.competency != "other"))[:6]
    rubric = await retriever.search_rubric_many(
        [(f"{job.title} interview questions {c}", c) for c in competencies]
        + [("behavioral interview teamwork conflict STAR", "behavioral")],
        level=rubric_level(difficulty),
        k=3,
    )
    bank = sorted(
        {
            " > ".join(c.content.splitlines()[0].split(" > ")[1:])
            for chunks in rubric
            for c in chunks
            if "Question bank" in c.content.splitlines()[0]
        }
    )
    resources = resources_for(set(competencies) | {"behavioral", "communication"})
    payload = {
        "job": {
            "title": job.title,
            "seniority": job.seniority,
            "responsibilities": job.responsibilities[:8],
        },
        "difficulty": difficulty,
        "gaps": [
            {
                "skill": g.skill,
                "importance": g.importance,
                "verdict": g.verdict,
                "competency": g.competency,
            }
            for g in gaps
        ],
        # Strong first; weak quotes let a weak candidate still get honest, grounded strengths.
        "evidence_quotes": [
            g.evidence_quote
            for verdict in ("strong_evidence", "weak_evidence")
            for g in gaps
            if g.verdict == verdict and g.evidence_quote
        ],
        "candidate_projects": [
            {"title": p.title, "stack": p.stack, "outcome": p.outcome} for p in cv.projects[:5]
        ],
        "question_bank_items": bank[:20],
        "ALLOWED_RESOURCES": [
            {"title": r.title, "url": r.url, "competency": r.competency} for r in resources
        ],
    }
    insights = await llm.structured(
        system=INSIGHTS_SYSTEM,
        # Job title, responsibilities, skill names and project text all come from the user's
        # CV / JD, so the whole payload is fenced as untrusted data.
        user=wrap_untrusted("analysis_data", json.dumps(payload, ensure_ascii=False)),
        schema=InsightsDraft,
        tier="strong",
        temperature=0.3,
        max_tokens=3500,
    )
    return sanitize_insights(insights, normalize(cv_text))


def sanitize_insights(insights: InsightsDraft, normalized_cv: str) -> Insights:
    """Enforce the rules the prompt asked for, in code: real quotes, curated URLs, 7 days."""
    allowed = allowed_urls()
    # A strength without a verifiable CV quote is an invented claim (seen live: "Foundational
    # Python knowledge" for a CV with no Python at all), so it is dropped, not shown unquoted.
    verified = [s for s in insights.strengths if quote_in_text(s.evidence_quote, normalized_cv)]
    strengths = verified[:5]
    days = insights.prep_plan[:7]
    plan = [
        PrepDay(
            day=i + 1,
            focus=d.focus,
            tasks=d.tasks[:4],
            resource_urls=[u for u in d.resource_urls if u in allowed][:3],
        )
        for i, d in enumerate(days)
    ]
    groups = [
        g.model_copy(update={"questions": g.questions[:4]}) for g in insights.likely_questions[:5]
    ]
    return Insights(strengths=strengths, likely_questions=groups, prep_plan=plan)


async def run_analysis(
    db: SupabaseRest,
    llm: LLMClient,
    embedder: Embedder,
    session: dict[str, Any],
) -> AsyncIterator[Event]:
    sid = UUID(session["id"])
    docs = await get_documents(db, sid)
    if "cv" not in docs or "jd" not in docs:
        raise AppError("documents_missing", "Upload your CV and paste the job description first.")
    cv_text = docs["cv"]["raw_text"]
    retriever = Retriever(db, embedder)

    yield "status", {"step": "extract", "message": "Reading your CV and the job description…"}
    cv, job = await extract_profiles(db, llm, docs)
    if not job.must_have_skills and not job.nice_to_have_skills:
        # Otherwise every coverage defaults to 1.0 and a non-JD text scores 100/100.
        raise AppError(
            "jd_no_skills",
            "We couldn't find any skills or requirements in this job description. "
            "Please paste the full posting, including the requirements section.",
        )
    yield (
        "profiles",
        {
            "role_title": job.title,
            "seniority": job.seniority,
            "must_have_count": len(job.must_have_skills),
            "nice_to_have_count": len(job.nice_to_have_skills),
            "candidate_name": cv.name,
        },
    )

    yield "status", {"step": "index", "message": "Indexing your CV for evidence search…"}
    await index_cv(db, embedder, docs["cv"])

    yield "status", {"step": "match", "message": "Checking each required skill against your CV…"}
    skills = [(s, "must_have") for s in job.must_have_skills] + [
        (s, "nice_to_have") for s in job.nice_to_have_skills
    ]
    gaps = await judge_skills(llm, retriever, sid, skills, cv_text)
    score, breakdown = compute_match(gaps, job.seniority, cv)
    yield "score", {"match_score": score, "breakdown": breakdown.model_dump()}
    yield "gaps", {"gaps": [g.model_dump() for g in gaps]}

    yield "status", {"step": "insights", "message": "Writing likely questions and your 7-day plan…"}
    insights = await build_insights(llm, retriever, cv, job, gaps, session["difficulty"], cv_text)
    yield "insights", insights.model_dump()

    analysis = Analysis(
        role_title=job.title,
        match_score=score,
        breakdown=breakdown,
        gaps=gaps,
        strengths=insights.strengths,
        likely_questions=insights.likely_questions,
        prep_plan=insights.prep_plan,
    )
    await db.insert(
        "gap_analyses",
        [
            {
                "session_id": str(sid),
                "match_score": score,
                "breakdown": breakdown.model_dump() | {"role_title": job.title},
                "gaps": [g.model_dump() for g in gaps],
                "strengths": [s.model_dump() for s in insights.strengths],
                "likely_questions": [q.model_dump() for q in insights.likely_questions],
                "prep_plan": [d.model_dump() for d in insights.prep_plan],
            }
        ],
        on_conflict="session_id",
    )
    await db.update(
        "sessions", {"id": f"eq.{sid}"}, {"status": "analyzed", "role_title": job.title[:200]}
    )
    log.info("analysis_done", extra={"extra_fields": {"session_id": str(sid), "score": score}})
    yield "done", analysis.model_dump()


def analysis_from_row(row: dict[str, Any]) -> Analysis:
    breakdown = dict(row["breakdown"])
    role_title = breakdown.pop("role_title", "")
    return Analysis.model_validate(
        {
            "role_title": role_title,
            "match_score": row["match_score"],
            "breakdown": breakdown,
            "gaps": row["gaps"],
            "strengths": row["strengths"],
            "likely_questions": row["likely_questions"],
            "prep_plan": row["prep_plan"],
        }
    )
