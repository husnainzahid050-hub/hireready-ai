"""Pydantic models for the mock interview: LLM output schemas and the public API contract.

LLM output models have NO defaults (strict structured output needs every field) and use string
enums ("1".."5") instead of ints: Groq once returned "6" (a string) for an int field, so we let the
schema constrain the token and convert to int in code.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.speech import SpeechMetrics

QuestionType = Literal["technical", "project", "gap_probe", "behavioral", "role_fit", "follow_up"]
MainQuestionType = Literal["technical", "project", "gap_probe", "behavioral", "role_fit"]
ScoreLabel = Literal["1", "2", "3", "4", "5"]
AnswerQuality = Literal["complete", "shallow", "off_topic"]

# ---------------------------------------------------------------- planning (LLM output)


class PlannedQuestionDraft(BaseModel):
    text: str = Field(description="The question, phrased naturally, as the interviewer says it")
    follow_up_hint: str = Field(description="What to probe if the answer is shallow (one line)")


class InterviewPlanDraft(BaseModel):
    opening: str = Field(description="One or two friendly sentences opening the interview")
    questions: list[PlannedQuestionDraft]


# ---------------------------------------------------------------- scoring (LLM output, SPEC 6.5)


class CriterionDraft(BaseModel):
    score: ScoreLabel
    justification: str = Field(description="One sentence")
    evidence_quote: str | None = Field(
        description="Short exact quote from the transcript supporting the score, or null"
    )


class AnswerEvaluationDraft(BaseModel):
    relevance: CriterionDraft
    technical_accuracy: CriterionDraft | None = Field(
        description="null for behavioral and role-fit questions"
    )
    depth: CriterionDraft
    structure: CriterionDraft = Field(description="For behavioral answers: use of STAR")
    communication: CriterionDraft
    what_interviewer_wanted: str
    improved_answer: str = Field(
        description="Concise, in the candidate's voice, using ONLY facts the candidate stated or "
        "that appear in their CV. Never invent experience."
    )
    one_tip: str
    feedback_summary: str = Field(description="One encouraging, honest sentence of feedback")
    answer_quality: AnswerQuality
    follow_up_question: str | None = Field(
        description="If shallow: one targeted follow-up that references what the candidate "
        "actually said. Otherwise null."
    )
    transition: str = Field(
        description="A short neutral acknowledgement before the next question, e.g. 'Thanks, "
        "that helps.' Never reveal or hint at a score."
    )


# ---------------------------------------------------------------- validated scores (stored)


class CriterionScore(BaseModel):
    score: int = Field(ge=1, le=5)
    justification: str
    evidence_quote: str | None
    quote_verified: bool


class AnswerScores(BaseModel):
    relevance: CriterionScore
    technical_accuracy: CriterionScore | None
    depth: CriterionScore
    structure: CriterionScore
    communication: CriterionScore
    average: float


class AnswerFeedback(BaseModel):
    summary: str
    tip: str
    what_interviewer_wanted: str
    improved_answer: str


# ---------------------------------------------------------------- API contract


class StartInterviewRequest(BaseModel):
    practice_mode: bool = False


class AnswerRequest(BaseModel):
    question_id: UUID
    text: str = Field(min_length=1, max_length=5000)


class QuestionOut(BaseModel):
    id: str
    order: int
    type: QuestionType
    competency: str | None
    text: str
    is_follow_up: bool


class Progress(BaseModel):
    answered: int
    total_planned: int


class FeedbackOut(BaseModel):
    summary: str
    tip: str


class LastAnswer(BaseModel):
    question_id: str
    transcript: str
    feedback: FeedbackOut | None
    # Phase 4 (voice): only present for audio answers (optional, so the text contract holds).
    speech_metrics: SpeechMetrics | None = None


class HistoryItem(BaseModel):
    question: QuestionOut
    answer_text: str


class InterviewTurn(BaseModel):
    status: Literal["interviewing", "completed"]
    practice_mode: bool
    progress: Progress
    question: QuestionOut | None
    last_answer: LastAnswer | None
    history: list[HistoryItem]
