"""Scored interview report (SPEC 6.5 / 6.6, Phase 5).

Pipeline (one run per session, cached after the first build):
 1. Load the questions + answers written during the interview (each answer was already scored per
    dimension, with verified evidence quotes, by the interviewer's `evaluate_answer` node).
 2. Deterministic part, NO LLM: weighted per-answer scores, answer level, follow-up handling,
    readiness score with its formula, band, the verdict the score implies, speech summary.
 3. ONE strong-model call (temperature 0.1) writes the employer view (verdict, hiring manager's
    reaction, green/red flags), cross-answer strengths / improvements and an updated 7-day plan.
 4. Guardrails in code: flag quotes must exist in the referenced answer's transcript, the verdict
    may move at most one step from what the score implies, plan URLs must be in the curated
    catalog. If the LLM call fails, a deterministic fallback report is built instead, so a finished
    interview always gets a report.

One run per session: the `reports` row itself is the lock. A claim is a placeholder row
`{"state": "generating"}` inserted WITHOUT upsert; the primary key on `session_id` makes the
insert fail for a second caller, which then waits for the first run. No extra SQL needed.
"""

import asyncio
import json
import math
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.client import DatabaseError, SupabaseRest
from app.schemas.analysis import PrepDay
from app.schemas.report import (
    AnswerLevel,
    AnswerSpeech,
    Band,
    DimensionScore,
    EmployerView,
    Flag,
    FlagDraft,
    FollowUpReport,
    QuestionReport,
    Readiness,
    Report,
    ReportSynthesisDraft,
    SpeechRow,
    SpeechSummary,
    Theme,
    ThemeDraft,
    Verdict,
)
from app.services.catalog import allowed_urls, resources_for
from app.services.evidence import normalize, quote_in_text
from app.services.llm import LLMClient, LLMError, wrap_untrusted

log = get_logger(__name__)

Event = tuple[str, dict[str, Any]]

# ------------------------------------------------------------------ the formula (shown to users)

# Per-answer dimension weights. Technical accuracy is N/A on behavioral / role-fit answers; the
# remaining weights are then renormalized so every answer is still scored out of 100.
DIMENSION_WEIGHTS: Final[dict[str, float]] = {
    "relevance": 0.20,
    "technical_accuracy": 0.25,
    "depth": 0.25,
    "structure": 0.15,
    "communication": 0.15,
}
DIMENSION_LABELS: Final[dict[str, str]] = {
    "relevance": "Relevance",
    "technical_accuracy": "Technical accuracy",
    "depth": "Depth",
    "structure": "Structure (STAR)",
    "communication": "Communication",
}
MAIN_WEIGHT, FOLLOW_UP_WEIGHT = 0.7, 0.3  # a question with a follow-up: 70% main + 30% follow-up
INTERVIEW_WEIGHT, MATCH_WEIGHT = 0.75, 0.25  # readiness = 75% interview + 25% CV match

# (minimum readiness, band, label, verdict the score implies), highest first.
BANDS: Final[list[tuple[int, Band, str, Verdict]]] = [
    (78, "strong", "Strong", "strong_yes"),
    (62, "interview_ready", "Interview-ready", "lean_yes"),
    (45, "getting_there", "Getting there", "lean_no"),
    (0, "not_ready", "Not ready yet", "no"),
]
VERDICT_ORDER: Final[list[Verdict]] = ["no", "lean_no", "lean_yes", "strong_yes"]
VERDICT_LABELS: Final[dict[str, str]] = {
    "strong_yes": "Strong yes",
    "lean_yes": "Lean yes",
    "lean_no": "Lean no",
    "no": "No",
}
# (minimum 1-5 average, level, label), highest first.
LEVELS: Final[list[tuple[float, AnswerLevel, str]]] = [
    (4.2, "senior", "Senior-level answer"),
    (3.4, "mid", "Mid-level answer"),
    (2.5, "junior", "Junior-level answer"),
    (0.0, "below_junior", "Below the junior bar"),
]
IDEAL_WPM = (120, 160)
NON_TECHNICAL_TYPES = {"behavioral", "role_fit"}

# Prompt budget (Groq free tier ~8K tokens/min per model): input ~3K tokens, output <= 3K.
MAX_TRANSCRIPT_CHARS_FOR_LLM = 600
MAX_QUESTION_CHARS_FOR_LLM = 220
SYNTHESIS_TIMEOUT_S = 45.0  # leave room inside the 60 s function limit for the fallback + save

# ------------------------------------------------------------------ claim / cache

CLAIM_TTL_S = 120  # a placeholder older than this belongs to a crashed / killed run
WAIT_POLL_S = 2.0
WAIT_TIMEOUT_S = 45.0
CLAIM: Final[dict[str, str]] = {"state": "generating"}


@dataclass
class ReportRow:
    state: str  # "generating" | "ready"
    report: Report | None
    share_token: str | None
    emailed_at: str | None
    created_at: str | None


async def load_row(db: SupabaseRest, session_id: UUID) -> ReportRow | None:
    rows = await db.select(
        "reports",
        {
            "select": "report,share_token,emailed_at,created_at",
            "session_id": f"eq.{session_id}",
            "limit": "1",
        },
    )
    if not rows:
        return None
    row = rows[0]
    data = row.get("report") or {}
    report = None
    if data.get("state") == "ready":
        try:
            report = Report.model_validate(data)
        except ValidationError:  # an older / corrupt shape: treat as missing, rebuild
            log.warning("report_invalid", extra={"extra_fields": {"session_id": str(session_id)}})
    return ReportRow(
        state="ready" if report else "generating",
        report=report,
        share_token=row.get("share_token"),
        emailed_at=row.get("emailed_at"),
        created_at=row.get("created_at"),
    )


def _is_stale(row: ReportRow) -> bool:
    if row.state != "generating" or not row.created_at:
        return False
    started = datetime.fromisoformat(row.created_at)
    return started < datetime.now(UTC) - timedelta(seconds=CLAIM_TTL_S)


async def claim(db: SupabaseRest, session_id: UUID) -> bool:
    """True if this request now owns the session's report build."""
    existing = await load_row(db, session_id)
    if existing is not None:
        if existing.report is not None or not _is_stale(existing):
            return False
        # Only a placeholder that is still stale is removed, never a finished report.
        cutoff = (datetime.now(UTC) - timedelta(seconds=CLAIM_TTL_S)).isoformat()
        await db.delete(
            "reports",
            {
                "session_id": f"eq.{session_id}",
                "report->>state": "eq.generating",
                "created_at": f"lt.{cutoff}",
            },
        )
    try:
        await db.insert(
            "reports",
            [
                {
                    "session_id": str(session_id),
                    "report": CLAIM,
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ],
        )
    except DatabaseError as exc:
        if exc.status_code == 409:  # unique violation: someone else claimed first
            return False
        raise
    return True


async def release(db: SupabaseRest, session_id: UUID) -> None:
    """Drop our placeholder if the run did not finish (a saved report is never touched)."""
    await db.delete(
        "reports", {"session_id": f"eq.{session_id}", "report->>state": "eq.generating"}
    )


async def save(db: SupabaseRest, session_id: UUID, report: Report) -> None:
    await db.update(
        "reports",
        {"session_id": f"eq.{session_id}"},
        {"report": report.model_dump(mode="json"), "created_at": datetime.now(UTC).isoformat()},
    )


async def wait_for_report(db: SupabaseRest, session_id: UUID) -> AsyncIterator[Event]:
    yield (
        "status",
        {
            "step": "waiting",
            "message": "Your report is already being written (maybe in another tab). Waiting…",
        },
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_TIMEOUT_S
    while True:
        row = await load_row(db, session_id)
        if row and row.report:
            yield "done", row.report.model_dump(mode="json")
            return
        if row is None:
            raise AppError("report_interrupted", "The other report run stopped. Please try again.")
        if loop.time() >= deadline:
            raise AppError(
                "report_in_progress",
                "Your report is still being written. Reload this page in a moment.",
            )
        await asyncio.sleep(WAIT_POLL_S)


# ------------------------------------------------------------------ loading interview data


class _Criterion(BaseModel):
    """Tolerant reader for the stored `answers.scores` jsonb (the interviewer may add fields)."""

    model_config = ConfigDict(extra="ignore")
    score: int
    justification: str = ""
    evidence_quote: str | None = None
    quote_verified: bool = False


@dataclass
class AnswerData:
    label: str
    question_id: str
    order: int
    type: str
    competency: str | None
    question: str
    transcript: str
    scores: dict[str, Any]
    feedback: dict[str, Any]
    is_follow_up: bool
    parent_id: str | None
    speech: AnswerSpeech | None


async def load_answers(db: SupabaseRest, session_id: UUID) -> list[AnswerData]:
    """Questions + answers in interview order, labelled Q1, Q1.1 (follow-up), Q2, ..."""
    questions = await db.select(
        "questions",
        {
            "select": "id,order_index,type,competency,text,parent_question_id,created_at",
            "session_id": f"eq.{session_id}",
            "order": "order_index.asc,created_at.asc",
        },
    )
    if not questions:
        return []
    ids = ",".join(str(q["id"]) for q in questions)
    answers = await db.select(
        "answers",
        {
            "select": "question_id,transcript,duration_seconds,words_per_minute,filler_count,"
            "filler_breakdown,long_pauses,scores,feedback",
            "question_id": f"in.({ids})",
        },
    )
    by_q = {str(a["question_id"]): a for a in answers}
    mains = sorted(
        (q for q in questions if not q.get("parent_question_id")),
        key=lambda q: int(q["order_index"]),
    )
    out: list[AnswerData] = []
    for i, main in enumerate(mains, start=1):
        group = [main] + [
            q for q in questions if str(q.get("parent_question_id") or "") == str(main["id"])
        ]
        for j, q in enumerate(group):
            a = by_q.get(str(q["id"]))
            if a is None or not a.get("scores"):
                continue  # never answered (or not scored): nothing to report on
            out.append(
                AnswerData(
                    label=f"Q{i}" if j == 0 else f"Q{i}.{j}",
                    question_id=str(q["id"]),
                    order=i,
                    type=str(q["type"]),
                    competency=q.get("competency"),
                    question=str(q["text"]),
                    transcript=str(a.get("transcript") or ""),
                    scores=dict(a["scores"]),
                    feedback=dict(a.get("feedback") or {}),
                    is_follow_up=j > 0,
                    parent_id=str(main["id"]) if j > 0 else None,
                    speech=_speech(a),
                )
            )
    return out


def _speech(a: dict[str, Any]) -> AnswerSpeech | None:
    if a.get("words_per_minute") is None and a.get("filler_count") is None:
        return None  # text answer
    return AnswerSpeech(
        duration_seconds=a.get("duration_seconds"),
        words_per_minute=a.get("words_per_minute"),
        filler_count=int(a.get("filler_count") or 0),
        filler_breakdown={k: int(v) for k, v in (a.get("filler_breakdown") or {}).items()},
        long_pauses=int(a.get("long_pauses") or 0),
    )


async def load_analysis(db: SupabaseRest, session_id: UUID) -> dict[str, Any] | None:
    rows = await db.select(
        "gap_analyses",
        {"select": "match_score,breakdown,gaps,prep_plan", "session_id": f"eq.{session_id}"},
    )
    return rows[0] if rows else None


# ------------------------------------------------------------------ deterministic scoring


def dimensions(a: AnswerData) -> list[DimensionScore]:
    out: list[DimensionScore] = []
    for key, weight in DIMENSION_WEIGHTS.items():
        raw = a.scores.get(key)
        crit: _Criterion | None = None
        if isinstance(raw, dict):
            try:
                crit = _Criterion.model_validate(raw)
            except ValidationError:
                crit = None
        if key == "technical_accuracy" and a.type in NON_TECHNICAL_TYPES:
            crit = None
        score = max(1, min(5, crit.score)) if crit else None
        out.append(
            DimensionScore(
                key=key,
                label=DIMENSION_LABELS[key],
                weight=weight,
                score=score,
                justification=crit.justification if crit else "Not applicable to this question.",
                evidence_quote=crit.evidence_quote if crit and crit.quote_verified else None,
            )
        )
    return out


def weighted_average(dims: list[DimensionScore]) -> float:
    """Weighted mean on the 1-5 scale; weights of N/A dimensions are renormalized away."""
    scored = [(d.score, d.weight) for d in dims if d.score is not None]
    if not scored:
        return 1.0
    total_w = sum(w for _, w in scored)
    return round(sum(s * w for s, w in scored) / total_w, 2)


def round_half_up(x: float) -> int:
    """Python's round() is banker's rounding (82.5 -> 82); users expect 82.5 -> 83. The inner
    round(.., 6) removes float noise first (4.3 is stored as 4.2999..)."""
    return math.floor(round(x, 6) + 0.5)


def to_100(avg_1_to_5: float) -> int:
    return round_half_up(max(0.0, min(1.0, (avg_1_to_5 - 1) / 4)) * 100)


def answer_level(avg: float) -> tuple[AnswerLevel, str]:
    for threshold, level, label in LEVELS:
        if avg >= threshold:
            return level, label
    return LEVELS[-1][1], LEVELS[-1][2]  # pragma: no cover


def band_for(score: int) -> tuple[Band, str, Verdict]:
    for threshold, band, label, verdict in BANDS:
        if score >= threshold:
            return band, label, verdict
    return BANDS[-1][1], BANDS[-1][2], BANDS[-1][3]  # pragma: no cover


def next_band(score: int) -> tuple[int, str] | None:
    """(threshold, label) of the band just above `score`, or None at the top band."""
    above = [(t, label) for t, _, label, _ in BANDS if t > score]
    return min(above) if above else None


def clamp_verdict(proposed: Verdict, implied: Verdict) -> Verdict:
    """The LLM may disagree with the score by at most one step (e.g. lean_no -> lean_yes)."""
    p, i = VERDICT_ORDER.index(proposed), VERDICT_ORDER.index(implied)
    return VERDICT_ORDER[max(i - 1, min(i + 1, p))]


def follow_up_handling(main_avg: float, fu_avg: float) -> str:
    delta = fu_avg - main_avg
    if delta >= 0.5:
        return (
            f"You recovered well: the follow-up answer scored {fu_avg:.1f}/5, up from "
            f"{main_avg:.1f}/5. Put that detail in your first answer next time."
        )
    if delta <= -0.5:
        return (
            f"The follow-up exposed a gap: it scored {fu_avg:.1f}/5 versus {main_avg:.1f}/5 "
            "for your first answer. Prepare one level deeper on this topic."
        )
    return (
        f"You held steady under the follow-up ({fu_avg:.1f}/5 vs {main_avg:.1f}/5). "
        "Adding a concrete example or number would have lifted it."
    )


def build_questions(answers: list[AnswerData]) -> list[QuestionReport]:
    cards: list[QuestionReport] = []
    mains = [a for a in answers if not a.is_follow_up]
    for main in mains:
        dims = dimensions(main)
        avg = weighted_average(dims)
        fu_data = next((a for a in answers if a.parent_id == main.question_id), None)
        follow_up = None
        combined = avg
        if fu_data is not None:
            fu_avg = weighted_average(dimensions(fu_data))
            combined = round(MAIN_WEIGHT * avg + FOLLOW_UP_WEIGHT * fu_avg, 2)
            follow_up = FollowUpReport(
                label=fu_data.label,
                question=fu_data.question,
                answer=fu_data.transcript,
                average=fu_avg,
                score=to_100(fu_avg),
                handling=follow_up_handling(avg, fu_avg),
                tip=str(fu_data.feedback.get("tip") or ""),
            )
        level, level_label = answer_level(combined)
        fb = main.feedback
        cards.append(
            QuestionReport(
                label=main.label,
                order=main.order,
                type=main.type,
                competency=main.competency,
                question=main.question,
                answer=main.transcript,
                dimensions=dims,
                average=avg,
                score=to_100(combined),
                level=level,
                level_label=level_label,
                summary=str(fb.get("summary") or ""),
                what_interviewer_wanted=str(fb.get("what_interviewer_wanted") or ""),
                improved_answer=str(fb.get("improved_answer") or ""),
                tip=str(fb.get("tip") or ""),
                follow_up=follow_up,
                speech=main.speech,
            )
        )
    return cards


def readiness(cards: list[QuestionReport], match_score: int | None) -> Readiness:
    interview = round_half_up(sum(c.score for c in cards) / len(cards)) if cards else 0
    if match_score is None:
        score = interview
        formula = f"Readiness = interview score {interview} (no CV match score available)"
        weights = {"interview": 1.0}
    else:
        score = round_half_up(INTERVIEW_WEIGHT * interview + MATCH_WEIGHT * match_score)
        formula = (
            f"Readiness = {INTERVIEW_WEIGHT:g} × interview score {interview} + "
            f"{MATCH_WEIGHT:g} × CV match {match_score} = {score}. Interview score = mean of "
            f"question scores; each answer is a weighted mean of its 1–5 dimension scores "
            f"(relevance 20%, technical accuracy 25%, depth 25%, structure 15%, communication 15%; "
            f"N/A dimensions renormalized), mapped to 0–100; a question with a follow-up counts "
            f"{MAIN_WEIGHT:.0%} main answer + {FOLLOW_UP_WEIGHT:.0%} follow-up."
        )
        weights = {"interview": INTERVIEW_WEIGHT, "cv_match": MATCH_WEIGHT}
    band, label, _ = band_for(score)
    nxt = next_band(score)
    return Readiness(
        score=score,
        band=band,
        band_label=label,
        interview_score=interview,
        match_score=match_score,
        formula=formula,
        weights=weights,
        next_band_label=nxt[1] if nxt else None,
        points_to_next_band=nxt[0] - score if nxt else None,
    )


def speech_summary(answers: list[AnswerData]) -> SpeechSummary | None:
    voiced = [a for a in answers if a.speech is not None]
    if not voiced:
        return None
    wpms = [a.speech.words_per_minute for a in voiced if a.speech and a.speech.words_per_minute]
    avg = round(sum(wpms) / len(wpms), 1) if wpms else None
    pace = None
    if avg is not None:
        pace = "slow" if avg < IDEAL_WPM[0] else "fast" if avg > IDEAL_WPM[1] else "ideal"
    fillers: dict[str, int] = {}
    for a in voiced:
        assert a.speech is not None  # noqa: S101
        for k, v in a.speech.filler_breakdown.items():
            fillers[k] = fillers.get(k, 0) + v
    total_fillers = sum(a.speech.filler_count for a in voiced if a.speech)
    pauses = sum(a.speech.long_pauses for a in voiced if a.speech)
    guidance = {
        None: "We couldn't measure your pace (too little speech).",
        "slow": f"You averaged {avg} WPM. A comfortable interview pace is roughly 120–160 WPM: "
        "try shorter pauses and fewer restarts.",
        "fast": f"You averaged {avg} WPM. A comfortable interview pace is roughly 120–160 WPM: "
        "slow down and pause after key points so they land.",
        "ideal": f"You averaged {avg} WPM, inside the comfortable 120–160 WPM range. Keep it up.",
    }[pace]
    return SpeechSummary(
        voice_answers=len(voiced),
        average_wpm=avg,
        pace=pace,
        guidance=guidance,
        filler_total=total_fillers,
        filler_breakdown=dict(sorted(fillers.items(), key=lambda kv: -kv[1])),
        long_pauses_total=pauses,
        rows=[
            SpeechRow(
                label=a.label,
                words_per_minute=a.speech.words_per_minute,
                filler_count=a.speech.filler_count,
                long_pauses=a.speech.long_pauses,
                duration_seconds=a.speech.duration_seconds,
            )
            for a in voiced
            if a.speech
        ],
    )


def open_gaps(analysis: dict[str, Any] | None) -> list[str]:
    if not analysis:
        return []
    return [
        str(g["skill"])
        for g in analysis.get("gaps") or []
        if g.get("importance") == "must_have" and g.get("verdict") != "strong_evidence"
    ][:8]


# ------------------------------------------------------------------ LLM synthesis

REPORT_SYSTEM = """You are the hiring manager who just finished a mock job interview, writing \
honest feedback for the candidate. You receive the per-answer scores (1-5 per dimension, already \
computed and final), the candidate's answers, the CV gaps and a list of allowed resources.

Rules:
- Do NOT re-score. `score_verdict` is what the scores imply; pick `verdict` equal to it unless \
the answers clearly justify one step up or down.
- hiring_manager_reaction: 3-5 sentences, first person ("I"), direct and fair, like a real \
debrief. Mention specific answers. No flattery, no generic advice, no invented facts.
- green_flags / red_flags: 3 each when possible. Each is tied to ONE answer label (e.g. "Q2", \
"Q3.1"). `quote` must be copied word for word from that answer's transcript (max 25 words), or \
null when the flag is about something missing.
- strengths / improvements: patterns across answers, each with the answer labels it is based on \
and one concrete next step.
- prep_plan: exactly 7 days, each with a focus, 2-4 small tasks, and resource_urls copied ONLY \
from ALLOWED_RESOURCES (or an empty list). Target the weakest answers and dimensions first.
- Talk about the ANSWER, never the person: "Q2 named the tool but not why you chose it", not \
"you lack depth" or "you seem nervous". No judgements of confidence, personality, accent or \
appearance.
- Each improvement starts with a verb and gives ONE next action. Calibrate to the role level \
("solid for a junior role"). No empty praise ("Great job!").
- prep_plan day 7 is always a re-test: redo a mock interview for this job and compare.
- Write in plain, simple English."""


def synthesis_payload(
    role_title: str,
    answers: list[AnswerData],
    cards: list[QuestionReport],
    ready: Readiness,
    implied: Verdict,
    gaps: list[str],
    difficulty: str,
) -> tuple[str, list[str]]:
    """Compact JSON payload (~3K tokens for 6 questions + follow-ups) and the allowed URLs."""
    level_by_label = {c.label: c.level for c in cards}
    items = []
    for a in answers:
        dims = dimensions(a)
        items.append(
            {
                "label": a.label,
                "type": a.type,
                "competency": a.competency,
                "question": a.question[:MAX_QUESTION_CHARS_FOR_LLM],
                "answer": a.transcript[:MAX_TRANSCRIPT_CHARS_FOR_LLM],
                "scores": {d.key: d.score for d in dims if d.score is not None},
                "weighted_1_to_5": weighted_average(dims),
                "level": level_by_label.get(a.label),
                "scorer_note": str(a.feedback.get("summary") or "")[:160],
            }
        )
    weak_comps = {
        c.competency for c in sorted(cards, key=lambda c: c.score)[:3] if c.competency
    } | {"behavioral", "communication"}
    resources = resources_for(weak_comps)[:14]
    payload = {
        "role_title": role_title,
        "difficulty": difficulty,
        "readiness_score": ready.score,
        "band": ready.band_label,
        "score_verdict": implied,
        "cv_gaps_must_have": gaps,
        "answers": items,
        "ALLOWED_RESOURCES": [{"title": r.title, "url": r.url} for r in resources],
    }
    return wrap_untrusted("analysis_data", json.dumps(payload, ensure_ascii=False)), [
        r.url for r in resources
    ]


def _flags(
    drafts: list[FlagDraft], answers: dict[str, AnswerData], *, limit: int = 3
) -> list[Flag]:
    out: list[Flag] = []
    seen: set[str] = set()
    for d in drafts:
        ref = d.answer_ref.strip().upper()
        a = answers.get(ref)
        if a is None or d.title.strip().lower() in seen:
            continue  # a flag must point at a real answer
        seen.add(d.title.strip().lower())
        verified = quote_in_text(d.quote, normalize(a.transcript))
        out.append(
            Flag(
                title=d.title.strip()[:120],
                detail=d.detail.strip()[:400],
                answer_ref=ref,
                question=a.question,
                quote=d.quote.strip() if verified and d.quote else None,
                quote_verified=verified,
            )
        )
        if len(out) == limit:
            break
    return out


def _themes(drafts: list[ThemeDraft], labels: set[str], limit: int = 4) -> list[Theme]:
    return [
        Theme(
            title=d.title.strip()[:120],
            detail=d.detail.strip()[:400],
            answer_refs=[r.strip().upper() for r in d.answer_refs if r.strip().upper() in labels],
        )
        for d in drafts[:limit]
        if d.title.strip()
    ]


def _plan(drafts: list[Any], fallback: list[PrepDay], offered: list[str]) -> list[PrepDay]:
    allowed = allowed_urls() & set(offered) if offered else allowed_urls()
    days = [
        PrepDay(
            day=i + 1,
            focus=str(d.focus)[:160],
            tasks=[str(t)[:240] for t in d.tasks[:4]],
            resource_urls=[u for u in d.resource_urls if u in allowed][:3],
        )
        for i, d in enumerate(drafts[:7])
    ]
    # Top up from the same days of the analysis plan if the model gave fewer than 7 days.
    for f in fallback[len(days) : 7]:
        days.append(f.model_copy(update={"day": len(days) + 1}))
    return days


def sanitize(
    draft: ReportSynthesisDraft,
    answers: list[AnswerData],
    implied: Verdict,
    fallback_plan: list[PrepDay],
    offered_urls: list[str],
) -> tuple[EmployerView, list[Theme], list[Theme], list[PrepDay]]:
    by_label = {a.label.upper(): a for a in answers}
    verdict = clamp_verdict(draft.verdict, implied)
    employer = EmployerView(
        verdict=verdict,
        verdict_label=VERDICT_LABELS[verdict],
        score_verdict=implied,
        reaction=draft.hiring_manager_reaction.strip()[:1200],
        green_flags=_flags(draft.green_flags, by_label),
        red_flags=_flags(draft.red_flags, by_label),
    )
    labels = set(by_label)
    return (
        employer,
        _themes(draft.strengths, labels),
        _themes(draft.improvements, labels),
        _plan(draft.prep_plan, fallback_plan, offered_urls),
    )


def fallback_synthesis(
    cards: list[QuestionReport], implied: Verdict, fallback_plan: list[PrepDay]
) -> tuple[EmployerView, list[Theme], list[Theme], list[PrepDay]]:
    """No LLM available: best/worst answers become flags, quoting verified scorer evidence."""
    ranked = sorted(cards, key=lambda c: c.score, reverse=True)

    def flag(c: QuestionReport, good: bool) -> Flag:
        dims = [d for d in c.dimensions if d.score is not None]
        d = max(dims, key=lambda x: x.score or 0) if good else min(dims, key=lambda x: x.score or 0)
        return Flag(
            title=f"{'Strong' if good else 'Weak'} {d.label.lower()} on {c.label}",
            detail=d.justification,
            answer_ref=c.label,
            question=c.question,
            quote=d.evidence_quote,
            quote_verified=d.evidence_quote is not None,
        )

    top = [c for c in ranked if c.score >= 50][:3]
    bottom = [c for c in reversed(ranked) if c.score < 75][:3]
    employer = EmployerView(
        verdict=implied,
        verdict_label=VERDICT_LABELS[implied],
        score_verdict=implied,
        reaction=(
            "This summary was generated from your scores only, because our AI writer was busy. "
            f"Your strongest answer was {ranked[0].label} and your weakest was {ranked[-1].label}; "
            "start your practice with the weakest one."
            if ranked
            else "No scored answers were found."
        ),
        green_flags=[flag(c, True) for c in top],
        red_flags=[flag(c, False) for c in bottom],
    )
    strengths = [
        Theme(title=c.level_label + f" on {c.label}", detail=c.summary, answer_refs=[c.label])
        for c in top[:2]
    ]
    improvements = [
        Theme(title=f"Rework your answer to {c.label}", detail=c.tip, answer_refs=[c.label])
        for c in bottom[:3]
    ]
    return employer, strengths, improvements, fallback_plan[:7]


# ------------------------------------------------------------------ the run


async def build_report(
    db: SupabaseRest, llm: LLMClient, session: dict[str, Any]
) -> AsyncIterator[Event]:
    sid = UUID(session["id"])
    yield "status", {"step": "collect", "message": "Collecting your answers and scores…"}
    answers, analysis = await asyncio.gather(load_answers(db, sid), load_analysis(db, sid))
    if not answers:
        raise AppError("no_answers", "We couldn't find any scored answers for this interview.", 409)
    role_title = str(
        session.get("role_title") or (analysis or {}).get("breakdown", {}).get("role_title") or ""
    )
    match_score = int(analysis["match_score"]) if analysis else None
    fallback_plan = [PrepDay.model_validate(d) for d in (analysis or {}).get("prep_plan") or []]
    gaps = open_gaps(analysis)

    cards = build_questions(answers)
    ready = readiness(cards, match_score)
    _, _, implied = band_for(ready.score)
    speech = speech_summary(answers)
    yield (
        "overview",
        {
            "readiness": ready.model_dump(),
            "score_verdict": implied,
            "questions": [c.model_dump() for c in cards],
            "speech": speech.model_dump() if speech else None,
        },
    )

    yield (
        "status",
        {"step": "synthesis", "message": "The hiring manager is writing their verdict…"},
    )
    user, offered = synthesis_payload(
        role_title, answers, cards, ready, implied, gaps, str(session.get("difficulty") or "junior")
    )
    generated_by = "llm"
    try:
        async with asyncio.timeout(SYNTHESIS_TIMEOUT_S):
            draft = await llm.structured(
                system=REPORT_SYSTEM,
                user=user,
                schema=ReportSynthesisDraft,
                tier="strong",
                temperature=0.1,
                max_tokens=3000,
            )
        employer, strengths, improvements, plan = sanitize(
            draft, answers, implied, fallback_plan, offered
        )
    except (LLMError, TimeoutError, ValidationError):
        log.warning("report_synthesis_fallback", extra={"extra_fields": {"session_id": str(sid)}})
        generated_by = "fallback"
        employer, strengths, improvements, plan = fallback_synthesis(cards, implied, fallback_plan)

    report = Report(
        generated_at=datetime.now(UTC).isoformat(),
        generated_by=generated_by,
        role_title=role_title,
        readiness=ready,
        employer=employer,
        questions=cards,
        speech=speech,
        strengths=strengths,
        improvements=improvements,
        open_gaps=gaps,
        prep_plan=plan,
    )
    await save(db, sid, report)
    log.info(
        "report_done",
        extra={
            "extra_fields": {
                "session_id": str(sid),
                "readiness": ready.score,
                "verdict": employer.verdict,
                "generated_by": generated_by,
            }
        },
    )
    yield "done", report.model_dump(mode="json")


# ------------------------------------------------------------------ sharing (redacted view)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")


def _phone(m: re.Match[str]) -> str:
    # Year ranges ("2019 - 2023") and scores look similar; a phone number has >= 10 digits.
    return "[phone removed]" if sum(c.isdigit() for c in m.group(0)) >= 10 else m.group(0)


def _scrub(text: str) -> str:
    return _PHONE_RE.sub(_phone, _EMAIL_RE.sub("[email removed]", text))


def shared_view(report: Report) -> dict[str, Any]:
    """Public copy: no session id, CV raw text or email ever lives in a report, and any email
    address or phone number the candidate SAID in an answer is masked as well."""

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return _scrub(node)
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node

    return dict(walk(report.model_dump(mode="json")))
