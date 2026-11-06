"""Pydantic models for intake and gap analysis.

Models used as LLM output schemas have NO defaults (strict structured output needs every
field present). Optional values are expressed as `X | None`.
"""

from typing import Literal

from pydantic import BaseModel, Field

Competency = Literal[
    "python", "sql", "machine_learning", "deep_learning", "nlp_llms", "data_handling",
    "apis_backend", "frontend_basics", "git_collaboration", "cloud_devops", "system_design",
    "behavioral", "communication", "problem_solving", "other",
]  # fmt: skip

Verdict = Literal["strong_evidence", "weak_evidence", "no_evidence"]
Seniority = Literal["intern", "junior", "mid", "senior", "unknown"]


# ---------------------------------------------------------------- extraction (LLM output)


class Education(BaseModel):
    degree: str
    institution: str
    year: str | None


class CVSkill(BaseModel):
    name: str
    evidence_sentence: str = Field(description="The exact sentence from the CV where it appears")


class Project(BaseModel):
    title: str
    stack: list[str]
    outcome: str | None


class Experience(BaseModel):
    role: str
    org: str
    duration: str | None
    bullets: list[str]


class CVProfile(BaseModel):
    name: str | None
    education: list[Education]
    skills: list[CVSkill]
    projects: list[Project]
    experience: list[Experience]
    certifications: list[str]


class JobSkill(BaseModel):
    name: str
    competency: Competency


class JobProfile(BaseModel):
    title: str
    seniority: Seniority
    must_have_skills: list[JobSkill]
    nice_to_have_skills: list[JobSkill]
    responsibilities: list[str]
    tools: list[str]
    soft_skills: list[str]


# ---------------------------------------------------------------- evidence judging (LLM output)


class SkillJudgement(BaseModel):
    skill: str
    verdict: Verdict
    evidence_quote: str | None = Field(
        description="Exact text copied from the CV evidence, or null when there is no evidence"
    )
    reason: str


class EvidenceJudgements(BaseModel):
    judgements: list[SkillJudgement]


# ---------------------------------------------------------------- insights (LLM output)


class Strength(BaseModel):
    title: str
    why_it_matters: str
    evidence_quote: str | None


class QuestionGroup(BaseModel):
    topic: str
    questions: list[str]


class PrepDayDraft(BaseModel):
    """LLM output: no day number. Code assigns days 1..7 (models sometimes emit "6" as a string)."""

    focus: str
    tasks: list[str]
    resource_urls: list[str]


class PrepDay(PrepDayDraft):
    day: int


class InsightsDraft(BaseModel):
    strengths: list[Strength]
    likely_questions: list[QuestionGroup]
    prep_plan: list[PrepDayDraft]


class Insights(BaseModel):
    strengths: list[Strength]
    likely_questions: list[QuestionGroup]
    prep_plan: list[PrepDay]


# ---------------------------------------------------------------- final analysis (API response)


class GapItem(BaseModel):
    skill: str
    importance: Literal["must_have", "nice_to_have"]
    competency: Competency
    verdict: Verdict
    evidence_quote: str | None
    reason: str
    quote_verified: bool


class ScoreComponent(BaseModel):
    weight: float
    score: float
    detail: str


class ScoreBreakdown(BaseModel):
    formula: str
    must_have: ScoreComponent
    nice_to_have: ScoreComponent
    seniority_fit: ScoreComponent


class Analysis(BaseModel):
    role_title: str
    match_score: int
    breakdown: ScoreBreakdown
    gaps: list[GapItem]
    strengths: list[Strength]
    likely_questions: list[QuestionGroup]
    prep_plan: list[PrepDay]
