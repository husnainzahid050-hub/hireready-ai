"""Pydantic models for intake and gap analysis.

Models used as LLM output schemas have NO defaults (strict structured output needs every
field present). Optional values are expressed as `X | None`.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.ats import AtsReport

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


MAX_CV_SKILLS = 30


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
    # Skill NAMES only. Evidence for each job skill comes from hybrid search over the CV text, so
    # asking the LLM for a quote per skill only bloated the output: a real 4.4K-char CV produced
    # 72 skills x ~250-char quotes, ran past the output limit on both providers, and failed.
    skills: list[str] = Field(
        description=f"Distinct skill names, most relevant first, max {MAX_CV_SKILLS}"
    )
    projects: list[Project]
    experience: list[Experience]
    certifications: list[str]

    @field_validator("skills", mode="before")
    @classmethod
    def _skill_names(cls, v: Any) -> Any:
        # Accept the old stored shape [{"name", "evidence_sentence"}] and cap the list.
        if isinstance(v, list):
            names = [s.get("name", "") if isinstance(s, dict) else s for s in v]
            seen: set[str] = set()
            out: list[str] = []
            for n in names:
                if isinstance(n, str) and n.strip() and n.strip().lower() not in seen:
                    seen.add(n.strip().lower())
                    out.append(n.strip())
            return out[:MAX_CV_SKILLS]
        return v


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
    # ATS readiness (knockout requirements). services/ats.py keeps only terms found in the JD.
    required_degrees: list[str] = Field(
        description="Degrees the JD requires, copied as written, e.g. \"Bachelor's degree in "
        'Computer Science". Empty if none.'
    )
    required_certifications: list[str] = Field(
        description="Certifications or licences the JD requires, copied as written. Empty if none."
    )
    min_years: int | None = Field(description="Minimum years of experience required, or null")
    work_authorization: str | None = Field(
        description="Work authorisation / visa / location requirement copied from the JD, or null"
    )

    @model_validator(mode="before")
    @classmethod
    def _pre_ats_cache(cls, v: Any) -> Any:
        # JD extractions are cached by content hash; ones saved before these fields existed
        # (and copied demo profiles) still validate. The LLM schema keeps them required.
        if isinstance(v, dict):
            v = dict(v)
            for key in ("required_degrees", "required_certifications"):
                v.setdefault(key, [])
            v.setdefault("min_years", None)
            v.setdefault("work_authorization", None)
        return v


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
    ats: AtsReport | None = None


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
    """API response. `ats` is None for analyses saved before the ATS check existed."""

    role_title: str
    match_score: int
    breakdown: ScoreBreakdown
    gaps: list[GapItem]
    strengths: list[Strength]
    likely_questions: list[QuestionGroup]
    prep_plan: list[PrepDay]
    ats: AtsReport | None = None
