"""End-to-end API tests with an in-memory fake database and a scripted fake LLM."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import make_docx
from tests.fakes import REAL_QUOTE, FakeDB, FakeLLM, install, sse_events


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    db, llm = FakeDB(), FakeLLM()
    install(monkeypatch, db, llm)
    return TestClient(app), db, llm


# ------------------------------------------------------------------ tests


def test_create_session_requires_consent(env) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = env
    r = client.post("/api/v1/sessions", json={"consent": False})
    assert r.status_code == 400 and r.json()["error"]["code"] == "consent_required"


def test_token_is_stored_hashed(env) -> None:  # type: ignore[no-untyped-def]
    client, db, _ = env
    r = client.post("/api/v1/sessions", json={"consent": True})
    assert r.status_code == 201
    token = r.json()["guest_token"]
    stored = db.rows("sessions")[0]["guest_token_hash"]
    assert token not in json.dumps(db.t) and len(stored) == 64


def test_demo_full_flow_streams_and_guards_quotes(env) -> None:  # type: ignore[no-untyped-def]
    client, db, llm = env
    s = client.post("/api/v1/sessions?demo=true", json={"consent": True}).json()
    h = {"X-Guest-Token": s["guest_token"]}

    r = client.post(f"/api/v1/sessions/{s['session_id']}/analyze", headers=h)
    assert r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    names = [e for e, _ in events]
    assert names[0] == "status" and names[-1] == "done"
    assert {"profiles", "score", "gaps", "insights"} <= set(names)

    done = events[-1][1]
    gaps = {g["skill"]: g for g in done["gaps"]}
    assert gaps["FastAPI"]["verdict"] == "strong_evidence" and gaps["FastAPI"]["quote_verified"]
    assert gaps["Docker"]["verdict"] == "no_evidence"  # hallucinated quote downgraded
    assert done["match_score"] == round(100 * (0.7 * 0.5 + 0.2 * 0.5 + 0.1))  # 55
    assert [d["day"] for d in done["prep_plan"]] == list(range(1, 8))

    # Judge prompt lists each excerpt once and references ids per skill.
    judge_prompt = llm.prompts[llm.calls.index("EvidenceJudgements")]
    assert "[E1]" in judge_prompt and "- FastAPI: check E1" in judge_prompt

    # Session marked analyzed; second analyze is served from cache (no new LLM calls).
    assert db.rows("sessions")[0]["status"] == "analyzed"
    n = len(llm.calls)
    again = sse_events(client.post(f"/api/v1/sessions/{s['session_id']}/analyze", headers=h).text)
    assert [e for e, _ in again] == ["done"] and len(llm.calls) == n

    got = client.get(f"/api/v1/sessions/{s['session_id']}/analysis", headers=h).json()
    assert got["analysis"]["role_title"] == "Junior AI Engineer" and got["session"]["is_demo"]


def test_wrong_or_missing_token_is_404(env) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = env
    s = client.post("/api/v1/sessions?demo=true", json={"consent": True}).json()
    for headers in ({"X-Guest-Token": "nope"}, {}):
        r = client.get(f"/api/v1/sessions/{s['session_id']}/analysis", headers=headers)
        assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"


def test_upload_documents_replaces_old_analysis(env) -> None:  # type: ignore[no-untyped-def]
    client, db, _ = env
    s = client.post("/api/v1/sessions", json={"consent": True}).json()
    h = {"X-Guest-Token": s["guest_token"]}
    cv = make_docx(["ALI RAZA", "Built a chatbot and " + REAL_QUOTE] + ["Python projects."] * 5)
    jd = "We need FastAPI and Docker skills. " * 10
    r = client.post(
        f"/api/v1/sessions/{s['session_id']}/documents",
        headers=h,
        files={"cv": ("cv.docx", cv, "application/octet-stream")},
        data={"jd_text": jd},
    )
    assert r.status_code == 200, r.text
    assert {d["kind"] for d in db.rows("documents")} == {"cv", "jd"}
    events = sse_events(client.post(f"/api/v1/sessions/{s['session_id']}/analyze", headers=h).text)
    assert events[-1][0] == "done" and db.rows("gap_analyses")

    # Re-upload => old analysis removed, so the next analyze recomputes.
    client.post(
        f"/api/v1/sessions/{s['session_id']}/documents",
        headers=h,
        files={"cv": ("cv.docx", cv, "application/octet-stream")},
        data={"jd_text": jd + " Also SQL."},
    )
    assert db.rows("gap_analyses") == []


def test_analysis_is_null_before_analyze(env) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = env
    s = client.post("/api/v1/sessions?demo=true", json={"consent": True}).json()
    r = client.get(
        f"/api/v1/sessions/{s['session_id']}/analysis", headers={"X-Guest-Token": s["guest_token"]}
    )
    assert r.status_code == 200 and r.json()["analysis"] is None


def test_analyze_without_documents_streams_error(env) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = env
    s = client.post("/api/v1/sessions", json={"consent": True}).json()
    events = sse_events(
        client.post(f"/api/v1/sessions/{s['session_id']}/analyze",
                    headers={"X-Guest-Token": s["guest_token"]}).text
    )  # fmt: skip
    assert events == [("error", {"code": "documents_missing", "message": events[0][1]["message"]})]
