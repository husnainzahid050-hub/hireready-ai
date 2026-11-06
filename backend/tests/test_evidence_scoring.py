from app.schemas.analysis import (
    CVProfile,
    Experience,
    GapItem,
    InsightsDraft,
    JobSkill,
    PrepDayDraft,
    QuestionGroup,
    SkillJudgement,
    Strength,
)
from app.services.analysis import sanitize_insights
from app.services.catalog import allowed_urls
from app.services.evidence import normalize, quote_in_text, validate_judgement
from app.services.scoring import compute_match

CV = (
    "Built a RAG chatbot — used “LangChain” and FAISS.\n• Served answers through a FastAPI backend."
)
NCV = normalize(CV)
SKILL = JobSkill(name="FastAPI", competency="apis_backend")


def test_normalize_handles_quotes_dashes_bullets_case() -> None:
    assert quote_in_text('built a rag chatbot - used "langchain" and faiss', NCV)
    assert quote_in_text("SERVED ANSWERS   through a FastAPI backend.", NCV)


def test_fabricated_quote_is_rejected() -> None:
    assert not quote_in_text("Deployed FastAPI on AWS with Docker", NCV)
    assert not quote_in_text("Fast", NCV)  # too short to count as evidence
    assert not quote_in_text(None, NCV)


def test_validate_judgement_downgrades_hallucinated_quote() -> None:
    j = SkillJudgement(
        skill="FastAPI",
        verdict="strong_evidence",
        evidence_quote="Led a FastAPI team of 5",
        reason="r",
    )
    verdict, quote, reason, verified = validate_judgement(j, SKILL, NCV)
    assert (verdict, quote, verified) == ("no_evidence", None, False)
    assert "could not be located" in reason


def test_validate_judgement_keeps_real_quote() -> None:
    j = SkillJudgement(
        skill="FastAPI",
        verdict="strong_evidence",
        evidence_quote="Served answers through a FastAPI backend.",
        reason="Used in project",
    )
    assert validate_judgement(j, SKILL, NCV)[0::3] == ("strong_evidence", True)


def test_missing_judgement_means_no_evidence() -> None:
    assert validate_judgement(None, SKILL, NCV)[0] == "no_evidence"


def gap(importance: str, verdict: str) -> GapItem:
    return GapItem(
        skill="s",
        importance=importance,  # type: ignore[arg-type]
        competency="python",
        verdict=verdict,  # type: ignore[arg-type]
        evidence_quote=None,
        reason="",
        quote_verified=False,
    )


EMPTY_CV = CVProfile(
    name=None, education=[], skills=[], projects=[], experience=[], certifications=[]
)


def test_match_formula() -> None:
    gaps = [gap("must_have", "strong_evidence"), gap("must_have", "no_evidence"),
            gap("nice_to_have", "weak_evidence")]  # fmt: skip
    score, b = compute_match(gaps, "junior", EMPTY_CV)
    # 100 * (0.7*0.5 + 0.2*0.5 + 0.1*1.0) = 55
    assert score == 55
    assert b.must_have.score == 0.5 and b.nice_to_have.score == 0.5 and b.seniority_fit.score == 1.0
    assert "1 strong, 0 weak, 1 missing" in b.must_have.detail


def test_no_nice_to_haves_reuses_must_coverage() -> None:
    score, b = compute_match([gap("must_have", "strong_evidence")], "junior", EMPTY_CV)
    assert score == 100 and "Using must-have coverage" in b.nice_to_have.detail


def test_seniority_fit_for_mid_role() -> None:
    _, b = compute_match([gap("must_have", "strong_evidence")], "mid", EMPTY_CV)
    assert b.seniority_fit.score == 0.5
    two_jobs = EMPTY_CV.model_copy(
        update={"experience": [Experience(role="r", org="o", duration=None, bullets=[])] * 2}
    )
    assert compute_match([], "mid", two_jobs)[1].seniority_fit.score == 1.0


def test_sanitize_insights_enforces_urls_quotes_and_days() -> None:
    real_url = sorted(allowed_urls())[0]
    draft = InsightsDraft(
        strengths=[
            Strength(title="RAG", why_it_matters="w", evidence_quote='used "langchain" and faiss'),
            Strength(
                title="Fake", why_it_matters="w", evidence_quote="Managed a team of 20 engineers"
            ),
        ],
        likely_questions=[QuestionGroup(topic="t", questions=["q1", "q2", "q3", "q4", "q5"])],
        prep_plan=[
            PrepDayDraft(
                focus=f"f{i}", tasks=["a"], resource_urls=[real_url, "https://evil.example/x"]
            )
            for i in range(9)
        ],
    )
    out = sanitize_insights(draft, NCV)
    assert out.strengths[0].evidence_quote is not None
    assert [s.title for s in out.strengths] == ["RAG"]  # strength with fabricated quote dropped
    assert [d.day for d in out.prep_plan] == [1, 2, 3, 4, 5, 6, 7]
    assert all(d.resource_urls == [real_url] for d in out.prep_plan)  # invented URL removed
    assert len(out.likely_questions[0].questions) == 4


def test_catalog_has_curated_urls() -> None:
    urls = allowed_urls()
    assert len(urls) > 20 and all(u.startswith("https://") for u in urls)


def test_internships_and_ta_jobs_do_not_count_for_mid_roles() -> None:
    # QA B9: an intern + a TA job made a fresh graduate a 100% fit for a "3+ years" role.
    def job(role: str) -> Experience:
        return Experience(role=role, org="o", duration=None, bullets=[])

    grad = EMPTY_CV.model_copy(
        update={"experience": [job("AI Engineering Intern"), job("Teaching Assistant, ML course")]}
    )
    _, b = compute_match([], "mid", grad)
    assert b.seniority_fit.score == 0.5 and "beyond internships" in b.seniority_fit.detail
    worked = EMPTY_CV.model_copy(update={"experience": [job("Backend Engineer"), job("TA")]})
    assert compute_match([], "mid", worked)[1].seniority_fit.score == 0.5  # "TA" is excluded
    worked.experience.append(job("International Sales Lead"))  # not an "intern" role
    assert compute_match([], "mid", worked)[1].seniority_fit.score == 1.0
