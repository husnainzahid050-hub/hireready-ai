"""QA regression tests built on the realistic fixtures in tests/fixtures (all fictional people).

Covers intake of odd/bad files, Unicode handling, the quote guard on real CV text, and the
bugs found during live QA (see docs/QA_REPORT.md).
"""

import json
import unicodedata
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.routers.sessions as sessions_router
from app.core.errors import AppError
from app.main import app
from app.schemas.analysis import (
    CVProfile,
    Experience,
    GapItem,
    InsightsDraft,
    JobProfile,
    PrepDayDraft,
    Strength,
)
from app.services.analysis import sanitize_insights
from app.services.evidence import normalize, quote_in_text
from app.services.llm import wrap_untrusted
from app.services.parsing import MAX_CV_CHARS, clean_text, extract_cv_text, validate_jd
from app.services.scoring import compute_match
from tests.fixtures.build_fixtures import LONG_MARKER_END, LONG_MARKER_MID
from tests.test_sessions_api import FakeDB, FakeEmbedder, FakeLLM, sse_events

FX = Path(__file__).parent / "fixtures"
FILES = FX / "files"


def read(name: str) -> bytes:
    return (FILES / name).read_bytes()


def text(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ intake


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("bad_scanned.pdf", "no_text"),
        ("bad_blank.pdf", "no_text"),
        ("bad_six_pages.pdf", "too_many_pages"),
        ("bad_encrypted.pdf", "encrypted_pdf"),
        ("bad_text_renamed.pdf", "unsupported_file"),
        ("bad_zip_renamed.docx", "unsupported_file"),
        ("bad_legacy.doc", "unsupported_file"),
        ("bad_image.png", "unsupported_file"),
    ],
)
def test_bad_files_get_clear_errors(name: str, code: str) -> None:
    with pytest.raises(AppError) as exc:
        extract_cv_text(read(name), None)
    assert exc.value.code == code and exc.value.status_code == 400


@pytest.mark.parametrize(
    "name",
    [
        "cv_strong_ai_grad.pdf",
        "cv_strong_ai_grad.docx",
        "cv_weak_marketing.docx",
        "cv_weak_marketing.pdf",
        "cv_senior_engineer.docx",
        "cv_senior_two_column.pdf",
        "cv_two_column_chrome.pdf",
        "cv_unicode_urdu.docx",
        "cv_unicode_urdu_chrome.pdf",
        "cv_injection.pdf",
        "cv_long_5_pages.pdf",
    ],
)
def test_good_fixtures_extract(name: str) -> None:
    assert len(extract_cv_text(read(name), None)) > 500


def test_over_2mb_rejected_with_413() -> None:
    big = read("cv_strong_ai_grad.pdf") + b"%" + b"0" * (2 * 1024 * 1024)
    with pytest.raises(AppError) as exc:
        extract_cv_text(big, "application/pdf")
    assert exc.value.code == "file_too_large" and exc.value.status_code == 413


def test_real_pdf_with_lying_mime_rejected() -> None:
    with pytest.raises(AppError, match="does not match"):
        extract_cv_text(read("cv_strong_ai_grad.pdf"), "image/png")


def test_long_cv_is_capped_and_mid_content_survives() -> None:
    out = extract_cv_text(read("cv_long.docx"), None)
    assert len(out) == MAX_CV_CHARS
    assert LONG_MARKER_MID in out and LONG_MARKER_END not in out  # tail silently dropped


def test_jd_fixtures_pass_validation() -> None:
    for name in ("jd_junior_ai_engineer.txt", "jd_mid_backend.txt", "jd_data_analyst.txt"):
        assert validate_jd(text(name))


# ------------------------------------------------------------------ Unicode (bug fix: NFKC)


def test_pdf_ligatures_are_folded() -> None:
    # Chrome/LaTeX PDFs extract "Staﬀ", "ﬁctional": full-text search for "fictional" missed them.
    out = extract_cv_text(read("cv_two_column_chrome.pdf"), None)
    assert "ﬀ" not in out and "ﬁ" not in out
    assert "Staff software engineer" in out and "(fictional)" in out
    assert clean_text("ﬁne-tuned a workﬂow") == "fine-tuned a workflow"


def test_urdu_text_survives_and_presentation_forms_fold() -> None:
    docx = extract_cv_text(read("cv_unicode_urdu.docx"), None)
    assert "عائشہ خان" in docx and "•" in docx and "▪" in docx
    pdf = extract_cv_text(read("cv_unicode_urdu_chrome.pdf"), None)
    forms = [ch for ch in pdf if "PRESENTATION FORM" in unicodedata.name(ch, "")]
    assert forms == [] and "عائشہ خان" in pdf


@pytest.mark.parametrize(
    "quote",
    [
        "Built SQL queries (CTEs, window functions) in PostgreSQL to track daily sales across 85 stores.",
        "• Built SQL queries (CTEs, window functions) in PostgreSQL",  # bullet kept by the model
        "Data Entry Intern - Sahara Microfinance",  # en dash typed as hyphen
        '"numbers first, story second"',  # straight quotes instead of curly
        "final-year thesis",  # ligature typed as plain letters
    ],
)
def test_quote_guard_accepts_unicode_variants(quote: str) -> None:
    cv = normalize(extract_cv_text(read("cv_unicode_urdu.docx"), None))
    assert quote_in_text(quote, cv)


@pytest.mark.xfail(
    strict=True, reason="OPEN: two-column PDFs merge side-by-side lines (QA_REPORT B6)"
)
def test_two_column_lines_are_not_merged() -> None:
    out = extract_cv_text(read("cv_senior_two_column.pdf"), None)
    assert "Python, Go, SQL - Lead 9 engineers" not in out


# ------------------------------------------------------------------ prompt injection


def test_injection_cv_cannot_close_the_data_tag() -> None:
    cv = extract_cv_text(read("cv_injection.pdf"), None)
    assert "ignore previous instructions" in cv.lower()  # hidden white text IS extracted
    wrapped = wrap_untrusted("cv", cv)
    assert wrapped.count("</cv>") == 1 and wrapped.endswith("</cv>")


# ------------------------------------------------------------------ scoring / insights fixes

EMPTY_CV = CVProfile(
    name=None, education=[], skills=[], projects=[], experience=[], certifications=[]
)


def _gap(verdict: str) -> GapItem:
    return GapItem(
        skill="Python", importance="must_have", competency="python",
        verdict=verdict, evidence_quote=None, reason="", quote_verified=False,  # type: ignore[arg-type]
    )  # fmt: skip


def test_senior_role_fit_depends_on_experience() -> None:
    role = Experience(role="r", org="o", duration=None, bullets=[])
    fits = [
        compute_match([_gap("strong_evidence")], "senior", EMPTY_CV.model_copy(
            update={"experience": [role] * n}))[1].seniority_fit.score
        for n in (0, 2, 3)
    ]  # fmt: skip
    assert fits == [0.25, 0.5, 1.0]  # was a flat 0.25 even for an 11-year staff engineer


def test_unquoted_strengths_are_dropped() -> None:
    # Live: a marketing CV with no Python got "Foundational Python knowledge" as a strength.
    cv = normalize(text("cv_weak_marketing.txt"))
    draft = InsightsDraft(
        strengths=[
            Strength(
                title="Foundational Python knowledge", why_it_matters="w", evidence_quote=None
            ),
            Strength(
                title="Presenting to audiences",
                why_it_matters="w",
                evidence_quote="Public speaking",
            ),
            Strength(title="ML", why_it_matters="w", evidence_quote="Trained ML models daily"),
        ],
        likely_questions=[],
        prep_plan=[PrepDayDraft(focus="f", tasks=["t"], resource_urls=[])] * 7,
    )
    assert [s.title for s in sanitize_insights(draft, cv).strengths] == ["Presenting to audiences"]


class NoSkillsLLM(FakeLLM):
    async def structured(self, *, system: str, user: str, schema: type, **kw: Any) -> Any:
        if schema is JobProfile:
            self.calls.append("JobProfile")
            return JobProfile(
                title="Unknown", seniority="unknown", must_have_skills=[],
                nice_to_have_skills=[], responsibilities=[], tools=[], soft_skills=[],
            )  # fmt: skip
        return await super().structured(system=system, user=user, schema=schema, **kw)


def test_jd_without_skills_is_an_error_not_a_perfect_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Live: a careers "about us" blurb extracted 0 skills and scored 100/100.
    db, llm = FakeDB(), NoSkillsLLM()
    monkeypatch.setattr(sessions_router, "get_db", lambda: db)
    monkeypatch.setattr(sessions_router, "get_llm", lambda: llm)
    monkeypatch.setattr(sessions_router, "get_embedder", lambda: FakeEmbedder())
    client = TestClient(app)
    s = client.post("/api/v1/sessions", json={"consent": True}).json()
    h = {"X-Guest-Token": s["guest_token"]}
    about_us = (
        "Thank you for visiting our careers page! Greenfield Grocers (fictional) was founded in "
        "2009 and now runs 120 stores. We believe in fresh food, fair prices and happy customers. "
        "Follow us on social media to hear about new store openings and seasonal promotions."
    )
    r = client.post(
        f"/api/v1/sessions/{s['session_id']}/documents",
        headers=h,
        files={"cv": ("cv.pdf", read("cv_strong_ai_grad.pdf"), "application/pdf")},
        data={"jd_text": about_us},
    )
    assert r.status_code == 200, r.text
    events = sse_events(client.post(f"/api/v1/sessions/{s['session_id']}/analyze", headers=h).text)
    assert [e for e, _ in events] == ["status", "error"]
    assert events[-1][1]["code"] == "jd_no_skills"
    assert "EvidenceJudgements" not in llm.calls and db.rows("gap_analyses") == []
    assert json.dumps(events)  # payloads are JSON-serializable
