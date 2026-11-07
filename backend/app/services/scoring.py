"""Deterministic, explainable scoring. No LLM here: the user can verify every number."""

import re

from app.schemas.analysis import (
    CVProfile,
    GapItem,
    ScoreBreakdown,
    ScoreComponent,
    Seniority,
    Verdict,
)

VERDICT_POINTS: dict[Verdict, float] = {
    "strong_evidence": 1.0,
    "weak_evidence": 0.5,
    "no_evidence": 0.0,
}
WEIGHTS = {"must_have": 0.7, "nice_to_have": 0.2, "seniority_fit": 0.1}
FORMULA = (
    "match = 100 x (0.7 x must-have coverage + 0.2 x nice-to-have coverage + 0.1 x seniority fit); "
    "coverage per skill: strong evidence = 1, weak = 0.5, none = 0"
)


def _coverage(items: list[GapItem]) -> float:
    if not items:
        return 1.0
    return sum(VERDICT_POINTS[i.verdict] for i in items) / len(items)


# Student jobs don't count towards "years of experience" for mid / senior roles (QA B9: an
# internship plus a TA job made a fresh graduate a 100% fit for a "3+ years" role).
_ENTRY_ROLE = re.compile(
    r"(?i:\b(intern(ship)?|trainee|apprentice|teaching assistant|student|volunteer)\b)|\bTA\b"
)


def professional_roles(cv: CVProfile) -> int:
    return sum(1 for e in cv.experience if not _ENTRY_ROLE.search(e.role))


def seniority_fit(job_seniority: Seniority, cv: CVProfile) -> tuple[float, str]:
    roles = professional_roles(cv)
    if job_seniority in ("intern", "junior", "unknown"):
        return 1.0, f"Role is {job_seniority}; entry-level candidates fit."
    if job_seniority == "mid":
        if roles >= 2:
            return 1.0, f"Mid-level role; CV lists {roles} roles."
        return 0.5, (
            f"Mid-level role; CV lists {roles} role(s) beyond internships, so experience may be "
            "light."
        )
    # Senior: previously a flat 0.25 even for a CV with many roles (an experienced senior
    # candidate was scored as a poor fit for a senior job).
    if roles >= 3:
        return 1.0, f"Senior role; CV lists {roles} roles."
    if roles == 2:
        return 0.5, f"Senior role; CV lists {roles} roles, so experience may be light."
    return 0.25, f"Senior role; CV lists {roles} role(s), so experience may be light."


def compute_match(
    gaps: list[GapItem], job_seniority: Seniority, cv: CVProfile
) -> tuple[int, ScoreBreakdown]:
    must = [g for g in gaps if g.importance == "must_have"]
    nice = [g for g in gaps if g.importance == "nice_to_have"]
    must_cov = _coverage(must)
    # No nice-to-haves listed => don't penalize; reuse must-have coverage.
    nice_cov = _coverage(nice) if nice else must_cov
    fit, fit_detail = seniority_fit(job_seniority, cv)

    raw = (
        WEIGHTS["must_have"] * must_cov
        + WEIGHTS["nice_to_have"] * nice_cov
        + WEIGHTS["seniority_fit"] * fit
    )
    score = round(100 * raw)

    def detail(items: list[GapItem], label: str) -> str:
        if not items:
            return f"No {label} skills listed in the job description."
        counts = {v: sum(1 for i in items if i.verdict == v) for v in VERDICT_POINTS}
        return (
            f"{counts['strong_evidence']} strong, {counts['weak_evidence']} weak, "
            f"{counts['no_evidence']} missing out of {len(items)} {label} skills"
        )

    breakdown = ScoreBreakdown(
        formula=FORMULA,
        must_have=ScoreComponent(
            weight=WEIGHTS["must_have"], score=round(must_cov, 3), detail=detail(must, "must-have")
        ),
        nice_to_have=ScoreComponent(
            weight=WEIGHTS["nice_to_have"],
            score=round(nice_cov, 3),
            detail=detail(nice, "nice-to-have")
            + ("" if nice else " Using must-have coverage instead."),
        ),
        seniority_fit=ScoreComponent(weight=WEIGHTS["seniority_fit"], score=fit, detail=fit_detail),
    )
    return max(0, min(100, score)), breakdown
