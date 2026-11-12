"""Pydantic models for the scored interview report (SPEC 6.5 / 6.6, Phase 5).

Two groups:
- `*Draft` models are the LLM output schema for the ONE synthesis call. No defaults (strict
  structured output needs every field) and string enums instead of ints.
- The rest is the stored / API shape. Numbers (scores, readiness, band, verdict bounds) are always
  computed in code from the per-answer scores saved during the interview, never by the LLM.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.analysis import PrepDay, PrepDayDraft

Verdict = Literal["strong_yes", "lean_yes", "lean_no", "no"]
Band = Literal["not_ready", "getting_there", "interview_ready", "strong"]
AnswerLevel = Literal["below_junior", "junior", "mid", "senior"]
Dimension = Literal["relevance", "technical_accuracy", "depth", "structure", "communication"]
PaceLabel = Literal["slow", "ideal", "fast"]

# ---------------------------------------------------------------- synthesis (LLM output)


class FlagDraft(BaseModel):
    title: str = Field(description="Short headline, max 8 words")
    detail: str = Field(description="One or two sentences, as the hiring manager would say it")
    answer_ref: str = Field(description="Label of the answer this is about, e.g. 'Q2' or 'Q2.1'")
    quote: str | None = Field(
        description="Short exact quote (max 25 words) copied from THAT answer, or null"
    )


class ThemeDraft(BaseModel):
    title: str = Field(description="Short headline, max 8 words")
    detail: str = Field(description="One or two sentences with a concrete next step")
    answer_refs: list[str] = Field(description="Answer labels this theme is based on")


class ReportSynthesisDraft(BaseModel):
    verdict: Verdict
    hiring_manager_reaction: str = Field(
        description="3-5 honest sentences in the first person, as the hiring manager reacting "
        "right after the interview. Specific, fair, no flattery, no invented facts."
    )
    green_flags: list[FlagDraft] = Field(description="Exactly 3 if possible, best first")
    red_flags: list[FlagDraft] = Field(description="Exactly 3 if possible, most serious first")
    strengths: list[ThemeDraft] = Field(description="2-4 strengths seen across the interview")
    improvements: list[ThemeDraft] = Field(
        description="2-4 improvement areas, most important first"
    )
    prep_plan: list[PrepDayDraft] = Field(
        description="Exactly 7 days targeting the weaknesses seen in THIS interview"
    )


# ---------------------------------------------------------------- stored / API shape


class DimensionScore(BaseModel):
    key: Dimension
    label: str
    weight: float
    score: int | None  # 1-5; None = not applicable (technical accuracy on behavioral answers)
    justification: str
    evidence_quote: str | None  # only quotes verified against the transcript during scoring


class AnswerSpeech(BaseModel):
    duration_seconds: float | None
    words_per_minute: float | None
    filler_count: int
    filler_breakdown: dict[str, int]
    long_pauses: int


class FollowUpReport(BaseModel):
    label: str
    question: str
    answer: str
    average: float  # 1-5
    score: int  # 0-100
    handling: str  # one plain-language line on how the follow-up went
    tip: str


class QuestionReport(BaseModel):
    label: str  # "Q1"
    order: int
    type: str
    competency: str | None
    question: str
    answer: str
    dimensions: list[DimensionScore]
    average: float  # weighted, 1-5 (main answer only)
    score: int  # 0-100, main answer combined with its follow-up (see formula)
    level: AnswerLevel
    level_label: str
    summary: str
    what_interviewer_wanted: str
    improved_answer: str
    tip: str
    follow_up: FollowUpReport | None
    speech: AnswerSpeech | None


class Readiness(BaseModel):
    score: int  # 0-100
    band: Band
    band_label: str
    interview_score: int
    match_score: int | None
    formula: str  # the exact arithmetic, shown to the user
    weights: dict[str, float]


class Flag(BaseModel):
    title: str
    detail: str
    answer_ref: str
    question: str
    quote: str | None
    quote_verified: bool


class EmployerView(BaseModel):
    verdict: Verdict
    verdict_label: str
    score_verdict: Verdict  # what the score alone implies; the LLM may move at most one step
    reaction: str
    green_flags: list[Flag]
    red_flags: list[Flag]


class Theme(BaseModel):
    title: str
    detail: str
    answer_refs: list[str]


class SpeechRow(BaseModel):
    label: str
    words_per_minute: float | None
    filler_count: int
    long_pauses: int
    duration_seconds: float | None


class SpeechSummary(BaseModel):
    voice_answers: int
    average_wpm: float | None
    pace: PaceLabel | None
    guidance: str
    filler_total: int
    filler_breakdown: dict[str, int]
    long_pauses_total: int
    rows: list[SpeechRow]


class Report(BaseModel):
    version: int = 1
    state: Literal["ready"] = "ready"
    generated_at: str
    generated_by: Literal["llm", "fallback"]
    role_title: str
    readiness: Readiness
    employer: EmployerView
    questions: list[QuestionReport]
    speech: SpeechSummary | None
    strengths: list[Theme]
    improvements: list[Theme]
    open_gaps: list[str]  # must-have skills the CV analysis found weak or missing
    prep_plan: list[PrepDay]


class ShareInfo(BaseModel):
    active: bool
    token: str | None
    path: str | None  # frontend path, e.g. "/r/<token>"


class ReportResponse(BaseModel):
    status: Literal["none", "generating", "ready"]
    report: Report | None
    share: ShareInfo
    email_configured: bool
    emailed_at: str | None


class ShareRequest(BaseModel):
    action: Literal["create", "revoke"] = "create"


class EmailRequest(BaseModel):
    # Optional: falls back to the address given at /start. Simple shape check like /sessions.
    email: str | None = Field(default=None, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailResponse(BaseModel):
    sent: bool
    emailed_at: str
