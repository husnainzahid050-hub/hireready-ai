"""ATS readiness through the API: upload signals, the `ats` SSE events, persistence, the
backfill for analyses saved before the check existed, and the demo cache."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.ats import AtsReport
from tests.fakes import FakeDB, FakeLLM, install, sse_events
from tests.test_ats import GOOD_CV, docx_bytes

URL = "/api/v1/sessions"
JD = "We need FastAPI and Docker skills for a Junior AI Engineer role. " * 6


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    db, llm = FakeDB(), FakeLLM()
    install(monkeypatch, db, llm)
    return TestClient(app), db, llm


def new_session(client: TestClient, demo: bool = False) -> tuple[str, dict[str, str]]:
    s = client.post(f"{URL}{'?demo=true' if demo else ''}", json={"consent": True}).json()
    return s["session_id"], {"X-Guest-Token": s["guest_token"]}


def cv_doc(db: FakeDB) -> dict[str, Any]:
    return next(d for d in db.rows("documents") if d["kind"] == "cv")


def test_analysis_streams_ats_after_profiles_and_after_gaps(env) -> None:  # type: ignore[no-untyped-def]
    client, db, llm = env
    sid, h = new_session(client, demo=True)
    events = sse_events(client.post(f"{URL}/{sid}/analyze", headers=h).text)
    names = [e for e, _ in events]
    first, second = (i for i, n in enumerate(names) if n == "ats")
    assert names[first - 1] == "profiles" and names[second - 1] == "gaps"
    early, late = (
        AtsReport.model_validate(events[first][1]),
        AtsReport.model_validate(events[second][1]),
    )
    assert early.score == late.score  # the gaps only add the (unscored) evidence overlay
    assert early.file_kind == "text" and 0 <= early.score <= 100
    done = dict(events)["done"]
    assert done["ats"] == events[second][1]
    # Persisted inside the breakdown jsonb (no migration) and restored on reload.
    row = db.rows("gap_analyses")[0]
    assert row["breakdown"]["ats"]["score"] == late.score
    saved = client.get(f"{URL}/{sid}/analysis", headers=h).json()["analysis"]
    assert saved["ats"] == done["ats"] and "ats" not in saved["breakdown"]
    assert llm.calls.count("JobProfile") == 1  # still no extra LLM call for the ATS check


def test_upload_stores_signals_and_header_contact_fails_r4(env) -> None:  # type: ignore[no-untyped-def]
    client, db, _ = env
    sid, h = new_session(client)
    body = [ln for ln in GOOD_CV.splitlines() if "@" not in ln]
    cv = docx_bytes(body, header="ali.raza@example.com | +92 300 1234567")
    r = client.post(
        f"{URL}/{sid}/documents", headers=h,
        files={"cv": ("final_v3.docx", cv, "application/octet-stream")}, data={"jd_text": JD},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    signals = cv_doc(db)["structured"]["ats_file"]
    assert signals["kind"] == "docx" and signals["contact_outside_body"] == "header_footer"
    assert signals["generic_file_name"] is True and "final_v3" not in str(signals)
    events = dict(sse_events(client.post(f"{URL}/{sid}/analyze", headers=h).text))
    ats = AtsReport.model_validate(events["done"]["ats"])
    assert next(c for c in ats.checks if c.id == "R4").status == "fail"
    # The profile is merged next to the signals, not written over them.
    assert "skills" in cv_doc(db)["structured"] and "ats_file" in cv_doc(db)["structured"]


def test_old_saved_analysis_gets_ats_backfilled(env) -> None:  # type: ignore[no-untyped-def]
    client, db, _ = env
    sid, h = new_session(client, demo=True)
    client.post(f"{URL}/{sid}/analyze", headers=h)
    row = db.rows("gap_analyses")[0]
    row["breakdown"].pop("ats")  # saved before the ATS check existed
    got = client.get(f"{URL}/{sid}/analysis", headers=h).json()["analysis"]
    assert got["ats"] and got["ats"]["score"] >= 0
    assert "ats" in row["breakdown"]  # saved back, so it's computed once
    again = sse_events(client.post(f"{URL}/{sid}/analyze", headers=h).text)
    assert [e for e, _ in again] == ["done"] and again[0][1]["ats"] == got["ats"]


def test_demo_cache_copy_without_ats_degrades_to_a_computed_one(env) -> None:  # type: ignore[no-untyped-def]
    client, db, llm = env
    sid, h = new_session(client, demo=True)
    client.post(f"{URL}/{sid}/analyze", headers=h)  # a first demo run fills the "cache"
    row = dict(db.rows("gap_analyses")[0])
    row["breakdown"] = {k: v for k, v in row["breakdown"].items() if k != "ats"}  # old cache row
    db.demo_cache = {k: v for k, v in row.items() if k != "session_id"}
    db.demo_structured = {
        d["kind"]: {k: v for k, v in d["structured"].items() if k != "ats_file"}  # old profiles
        for d in db.rows("documents")
    }
    llm.calls.clear()
    sid2, h2 = new_session(client, demo=True)
    events = sse_events(client.post(f"{URL}/{sid2}/analyze", headers=h2).text)
    assert [e for e, _ in events] == ["done"] and llm.calls == []
    assert events[0][1]["ats"]["file_kind"] == "text"  # demo falls back to the sample signals


def test_ats_failure_never_breaks_a_saved_analysis(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import app.services.analysis as analysis_service

    client, db, _ = env
    sid, h = new_session(client, demo=True)
    client.post(f"{URL}/{sid}/analyze", headers=h)
    db.rows("gap_analyses")[0]["breakdown"].pop("ats")

    def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setattr(analysis_service, "ats_report", boom)
    got = client.get(f"{URL}/{sid}/analysis", headers=h).json()["analysis"]
    assert got["ats"] is None and got["match_score"] >= 0
