"""Interview graph state.

The whole state is ONE JSON document stored in `interview_state.state` (jsonb). Each HTTP request
loads it, runs the graph for exactly one turn, and saves it back: nothing lives in memory between
requests, so any serverless instance can handle the next answer.

Fields are split in two groups:
- persisted: survives between requests (plan, pending question, history, scores, status),
- per-request ("turn input/output"): set before a run and cleared before saving
  (`clear_transient`), e.g. the submitted answer and the rows to write to the database.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.db.client import SupabaseRest
from app.schemas.analysis import CVProfile, GapItem, JobProfile
from app.schemas.interview import (
    AnswerFeedback,
    AnswerQuality,
    AnswerScores,
    MainQuestionType,
    QuestionType,
)
from app.services.llm import LLMClient
from app.services.retrieval import Retriever

STATE_VERSION = 1
MAX_FOLLOW_UPS_PER_QUESTION = 1

Event = Literal["start", "answer"]
Route = Literal["follow_up", "next", "finish"]


class RubricSnippet(BaseModel):
    id: str
    content: str


class PlannedQuestion(BaseModel):
    id: str
    order: int  # 1-based main question number
    type: MainQuestionType
    competency: str | None
    focus: str  # skill / project / theme this question is about
    text: str
    follow_up_hint: str
    rubric: list[RubricSnippet]  # prefetched at planning time: no retrieval per answer

    @property
    def rubric_chunk_ids(self) -> list[str]:
        return [r.id for r in self.rubric]


class AskedQuestion(BaseModel):
    """A question that was put to the candidate (main or follow-up)."""

    id: str
    order: int
    type: QuestionType
    competency: str | None
    text: str
    is_follow_up: bool
    parent_id: str | None


class Turn(BaseModel):
    question: AskedQuestion
    answer_id: str
    answer_text: str
    scores: AnswerScores | None
    feedback: AnswerFeedback | None


class NewAnswer(BaseModel):
    """Row to insert into `answers` after the run."""

    id: str
    question_id: str
    transcript: str
    scores: AnswerScores
    feedback: AnswerFeedback
    # Phase 4 (voice): speech metrics, set by the service after the run; null for text answers.
    duration_seconds: float | None = None
    words_per_minute: float | None = None
    filler_count: int | None = None
    filler_breakdown: dict[str, int] | None = None
    long_pauses: int | None = None


class InterviewState(BaseModel):
    # ---- persisted
    version: int = STATE_VERSION
    session_id: str
    practice_mode: bool = False
    difficulty: Literal["junior", "mid"] = "junior"
    interview_type: Literal["technical", "behavioral", "mixed"] = "mixed"
    status: Literal["planning", "interviewing", "completed"] = "planning"
    plan: list[PlannedQuestion] = []
    plan_index: int = 0  # index of the current main question in `plan`
    current: AskedQuestion | None = None  # the question waiting for an answer
    follow_up_counts: dict[str, int] = {}  # main question id -> follow-ups asked
    history: list[Turn] = []
    report_pending: bool = False  # set by `finish`; Phase 5 generates the report

    # ---- per-request (cleared before saving)
    event: Event | None = None
    answer_text: str | None = None
    route: Route | None = None
    answer_quality: AnswerQuality | None = None
    transition: str | None = None  # neutral acknowledgement before the next question
    follow_up_text: str | None = None
    new_questions: list[AskedQuestion] = []
    new_planned: list[PlannedQuestion] = []
    new_answer: NewAnswer | None = None

    def clear_transient(self) -> "InterviewState":
        return self.model_copy(
            update={
                "event": None,
                "answer_text": None,
                "route": None,
                "answer_quality": None,
                "transition": None,
                "follow_up_text": None,
                "new_questions": [],
                "new_planned": [],
                "new_answer": None,
            }
        )

    def answered_main(self) -> int:
        return sum(1 for t in self.history if not t.question.is_follow_up)


@dataclass
class InterviewContext:
    """Dependencies and read-only inputs for one run (LangGraph runtime context, not state)."""

    llm: LLMClient
    retriever: Retriever
    db: SupabaseRest
    cv: CVProfile
    job: JobProfile
    gaps: list[GapItem]
