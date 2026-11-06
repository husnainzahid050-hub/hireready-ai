"""One analysis run per session (QA B3), time budget + "still working" notices (QA B8), and the
small intake fixes (QA B12). Fake DB / LLM from tests/fakes.py."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import app.routers.sessions as sessions_router
import app.services.analysis as analysis_service
from app.core.quotas import SESSION_QUOTAS
from app.core.sse import BudgetExceededError, paced
from app.main import app
from app.services.llm import LLMClient
from tests.fakes import FakeDB, FakeLLM, install, sse_events
from tests.test_llm import GOOD, SETTINGS, Out, gemini_ok

URL = "/api/v1/sessions"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    db, llm = FakeDB(), FakeLLM()
    install(monkeypatch, db, llm)
    monkeypatch.setattr(analysis_service, "WAIT_POLL_S", 0.01)
    return TestClient(app), db, llm


def demo_session(client: TestClient) -> tuple[str, dict[str, str]]:
    s = client.post(f"{URL}?demo=true", json={"consent": True}).json()
    return s["session_id"], {"X-Guest-Token": s["guest_token"]}


def session_row(db: FakeDB) -> dict[str, Any]:
    return db.rows("sessions")[0]


def ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


# ------------------------------------------------------------------ one run per session (B3)


class SlowLLM(FakeLLM):
    """Yields to the event loop on every call, so two requests really overlap."""

    async def structured(self, **kw: Any) -> Any:
        await asyncio.sleep(0.05)
        return await super().structured(**kw)


async def test_concurrent_analyze_runs_the_pipeline_once(monkeypatch: pytest.MonkeyPatch) -> None:
    db, llm = FakeDB(), SlowLLM()
    install(monkeypatch, db, llm)
    monkeypatch.setattr(analysis_service, "WAIT_POLL_S", 0.01)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        s = (await client.post(f"{URL}?demo=true", json={"consent": True})).json()
        h = {"X-Guest-Token": s["guest_token"]}
        a, b = await asyncio.gather(
            client.post(f"{URL}/{s['session_id']}/analyze", headers=h),
            client.post(f"{URL}/{s['session_id']}/analyze", headers=h),
        )
    runs = sorted((sse_events(a.text), sse_events(b.text)), key=len)
    waiter, runner = runs
    assert [e for e, _ in waiter] == ["status", "done"] and waiter[0][1]["step"] == "waiting"
    assert runner[-1][0] == "done" and "gaps" in [e for e, _ in runner]
    assert waiter[-1][1] == runner[-1][1]  # both tabs show the same, single result
    assert llm.calls.count("CVProfile") == 1 and llm.calls.count("EvidenceJudgements") == 1
    assert db.usage[(s["session_id"], "analysis")] == 1  # the waiter costs no quota
    assert session_row(db)["analysis_started_at"] is None  # claim released


def test_waiter_reports_an_interrupted_run(env) -> None:  # type: ignore[no-untyped-def]
    client, db, llm = env
    sid, h = demo_session(client)
    session_row(db)["analysis_started_at"] = ago(1)  # another request holds the claim

    polls = 0
    original = db.select

    async def select(table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        nonlocal polls
        if table == "sessions" and params.get("select") == "analysis_started_at":
            polls += 1
            if polls == 2:  # the other run crashes and releases its claim
                session_row(db)["analysis_started_at"] = None
        return await original(table, params)

    db.select = select  # type: ignore[method-assign]
    events = sse_events(client.post(f"{URL}/{sid}/analyze", headers=h).text)
    assert [e for e, _ in events] == ["status", "error"]
    assert events[-1][1]["code"] == "analysis_interrupted" and llm.calls == []


def test_waiter_gives_up_after_its_timeout(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, db, llm = env
    monkeypatch.setattr(analysis_service, "WAIT_TIMEOUT_S", 0.05)
    sid, h = demo_session(client)
    session_row(db)["analysis_started_at"] = ago(1)
    events = sse_events(client.post(f"{URL}/{sid}/analyze", headers=h).text)
    assert [e for e, _ in events] == ["status", "error"]
    assert events[-1][1]["code"] == "analysis_in_progress"
    assert llm.calls == [] and session_row(db)["analysis_started_at"] is not None  # not ours


def test_stale_claim_is_taken_over(env) -> None:  # type: ignore[no-untyped-def]
    client, db, llm = env
    sid, h = demo_session(client)
    session_row(db)["analysis_started_at"] = ago(analysis_service.CLAIM_TTL_S + 60)  # crashed run
    events = sse_events(client.post(f"{URL}/{sid}/analyze", headers=h).text)
    assert events[-1][0] == "done" and "CVProfile" in llm.calls
    assert session_row(db)["analysis_started_at"] is None


def test_claim_is_released_after_errors_and_quota_rejections(env) -> None:  # type: ignore[no-untyped-def]
    client, db, _ = env
    s = client.post(URL, json={"consent": True}).json()  # no documents uploaded
    sid, h = s["session_id"], {"X-Guest-Token": s["guest_token"]}
    events = sse_events(client.post(f"{URL}/{sid}/analyze", headers=h).text)
    assert events[-1][1]["code"] == "documents_missing"
    assert session_row(db)["analysis_started_at"] is None  # can retry right away

    db.usage[(sid, "analysis")] = SESSION_QUOTAS["analysis"]
    r = client.post(f"{URL}/{sid}/analyze", headers=h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded"
    assert session_row(db)["analysis_started_at"] is None


def test_saved_analysis_needs_no_claim(env) -> None:  # type: ignore[no-untyped-def]
    client, db, _ = env
    sid, h = demo_session(client)
    client.post(f"{URL}/{sid}/analyze", headers=h)
    db.rpc_calls.clear()
    again = sse_events(client.post(f"{URL}/{sid}/analyze", headers=h).text)
    assert [e for e, _ in again] == ["done"] and db.rpc_calls == []


# ------------------------------------------------------------------ time budget (B8)


class HangingLLM(FakeLLM):
    async def structured(self, **kw: Any) -> Any:
        await asyncio.sleep(10)
        raise AssertionError("should have been cancelled")


def test_slow_pipeline_warns_then_stops_at_the_budget(env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, db, _ = env
    install(monkeypatch, db, HangingLLM())
    monkeypatch.setattr(sessions_router, "ANALYSIS_BUDGET_S", 0.3)
    monkeypatch.setattr(sessions_router, "SLOW_AFTER_S", 0.05)
    sid, h = demo_session(client)
    events = sse_events(client.post(f"{URL}/{sid}/analyze", headers=h).text)
    steps = [p.get("step") for e, p in events if e == "status"]
    assert steps == ["extract", "slow"]
    assert events[-1][0] == "error" and events[-1][1]["code"] == "analysis_timeout"
    assert session_row(db)["analysis_started_at"] is None and db.rows("gap_analyses") == []


async def _collect(events: Any) -> list[Any]:
    return [e async for e in events]


SLOW = ("status", {"step": "slow"})


async def test_paced_warns_once_per_step_on_fallback() -> None:
    fallbacks = 0

    async def pipeline() -> Any:
        nonlocal fallbacks
        yield "status", {"step": "a"}
        fallbacks += 1  # the LLM switched provider while working on step b
        await asyncio.sleep(0.05)
        fallbacks += 1
        await asyncio.sleep(0.05)
        yield "done", {}

    out = await _collect(
        paced(
            pipeline(),
            budget_s=5,
            slow_after_s=60,
            slow_event=SLOW,
            fallbacks=lambda: fallbacks,
            poll_s=0.01,
        )
    )
    assert out == [("status", {"step": "a"}), SLOW, ("done", {})]


async def test_paced_budget_cancels_and_closes_the_producer() -> None:
    closed = False

    async def pipeline() -> Any:
        nonlocal closed
        try:
            yield "status", {"step": "a"}
            await asyncio.sleep(10)
            yield "done", {}
        finally:
            closed = True

    with pytest.raises(BudgetExceededError):
        await _collect(paced(pipeline(), budget_s=0.05, slow_after_s=60, slow_event=SLOW))
    assert closed


async def test_paced_passes_producer_errors_through() -> None:
    async def pipeline() -> Any:
        yield "status", {}
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await _collect(paced(pipeline(), budget_s=5, slow_after_s=60, slow_event=SLOW))


async def test_llm_provider_time_is_bounded_and_fallback_is_counted() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        if "groq" in req.url.host:
            await asyncio.sleep(5)  # Groq hangs
        return gemini_ok(GOOD)

    llm = LLMClient(
        SETTINGS,
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        provider_timeout_s=0.1,
    )
    started = asyncio.get_running_loop().time()
    out = await llm.structured(system="s", user="u", schema=Out)
    assert out.title == "ok" and llm.fallbacks == 1
    assert asyncio.get_running_loop().time() - started < 1


# ------------------------------------------------------------------ small intake fixes (B12)


def test_malformed_session_id_is_404_not_422(env) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = env
    for method, path in (("get", "/analysis"), ("post", "/analyze"), ("get", "/interview")):
        r = getattr(client, method)(f"{URL}/not-a-uuid{path}", headers={"X-Guest-Token": "x"})
        assert r.status_code == 404 and r.json()["error"]["code"] == "session_not_found"


def test_very_long_jd_gets_the_specific_error(env) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = env
    s = client.post(URL, json={"consent": True}).json()
    r = client.post(
        f"{URL}/{s['session_id']}/documents",
        headers={"X-Guest-Token": s["guest_token"]},
        files={"cv": ("cv.pdf", b"%PDF-1.4", "application/pdf")},
        data={"jd_text": "Python developer needed. " * 1000},  # 25k chars
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "jd_too_long"
