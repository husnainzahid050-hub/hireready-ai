"""Phase 7: rate-limit backends and outage modes, client IP through the proxy, the global daily
LLM budget, the demo cache, and fail-fast production config."""

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import app.core.budget as budget
import app.core.redis as redis_mod
from app.core.config import Settings
from app.core.rate_limit import (
    InMemoryRateLimiter,
    Policy,
    UpstashRateLimiter,
    client_ip_with_source,
)
from app.main import app, check_startup
from tests.fakes import FakeDB, FakeLLM, install, sse_events


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": raw, "client": ("10.0.0.1", 1)})


# ------------------------------------------------------------------ limiter backends


async def test_in_memory_limiter_is_a_fixed_window() -> None:
    clock = {"t": 7200.0 + 100}
    limiter = InMemoryRateLimiter(now=lambda: clock["t"])
    p = Policy(limit=2, window_s=3600)
    assert [(await limiter.hit("k", p)).allowed for _ in range(3)] == [True, True, False]
    assert (await limiter.hit("k", p)).retry_after_s == 3500
    assert (await limiter.hit("other", p)).allowed  # keys are independent
    clock["t"] += 3600  # next window
    assert (await limiter.hit("k", p)).allowed


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("open", [True, True, True]),
        ("closed", [False, False, False]),
        ("local", [True, False, False]),
    ],
)
async def test_upstash_outage_mode_per_policy(mode: Any, expected: list[bool]) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    limiter = UpstashRateLimiter("https://x.upstash.io", "tok", client, now=lambda: 1000.0)
    p = Policy(limit=1, window_s=60, on_outage=mode)
    assert [(await limiter.hit("k", p)).allowed for _ in range(3)] == expected


def test_default_backend_without_upstash_is_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeDB(), FakeLLM())
    client = TestClient(app)
    codes = [client.post("/api/v1/sessions", json={"consent": True}).status_code for _ in range(11)]
    assert codes[:10] == [201] * 10 and codes[10] == 429  # session_create: 10/hour per IP


# ------------------------------------------------------------------ client IP


def test_proxy_ip_header_needs_the_shared_secret() -> None:
    s = Settings(client_ip_header_secret="proxy-secret")
    good = {"x-hireready-client-ip": "203.0.113.9", "x-hireready-proxy-secret": "proxy-secret"}
    vercel = {"x-forwarded-for": "198.51.100.1"}
    assert client_ip_with_source(_request({**good, **vercel}), s) == ("203.0.113.9", "proxy")
    forged = {**good, "x-hireready-proxy-secret": "guess", **vercel}
    assert client_ip_with_source(_request(forged), s) == ("198.51.100.1", "x-forwarded-for")
    # Secret not configured: the header is ignored entirely.
    assert client_ip_with_source(_request({**good, **vercel}), Settings())[1] == "x-forwarded-for"
    assert client_ip_with_source(_request(), Settings()) == ("10.0.0.1", "socket")


def test_client_ip_endpoint_reports_source() -> None:
    r = TestClient(app).get("/api/v1/health/client-ip", headers={"x-forwarded-for": "192.0.2.4"})
    assert r.json() == {"ip": "192.0.2.4", "source": "x-forwarded-for"}
    assert r.headers["cache-control"] == "no-store"


# ------------------------------------------------------------------ global LLM budget


async def test_budget_soft_limit_pauses_demo_hard_limit_stops_everyone() -> None:
    s = Settings(llm_daily_budget=10, llm_daily_soft_ratio=0.5)
    now = lambda: 86400 * 100 + 3600.0  # noqa: E731  (01:00 UTC)
    await budget.reserve_llm_calls("analysis", demo=True, settings=s, now=now)  # 4 <= 5
    with pytest.raises(budget.BudgetExhaustedError) as soft:
        await budget.reserve_llm_calls("analysis", demo=True, settings=s, now=now)  # 8 > 5
    assert "demo" in soft.value.message
    await budget.reserve_llm_calls("report", settings=s, now=now)  # 9: real users continue
    await budget.reserve_llm_calls("report", settings=s, now=now)  # 10
    with pytest.raises(budget.BudgetExhaustedError) as hard:
        await budget.reserve_llm_calls("report", settings=s, now=now)
    assert hard.value.status_code == 503
    assert hard.value.headers == {"Retry-After": str(23 * 3600)}
    # A new UTC day starts from zero.
    await budget.reserve_llm_calls("report", settings=s, now=lambda: 86400 * 101 + 5.0)


async def test_budget_uses_redis_and_falls_back_when_it_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Any] = []

    def ok(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content))
        return httpx.Response(200, json=[{"result": 999}, {"result": 1}])

    r = redis_mod.UpstashRedis(
        "https://r.io", "t", httpx.AsyncClient(transport=httpx.MockTransport(ok))
    )
    monkeypatch.setattr(budget, "get_redis", lambda: r)
    with pytest.raises(budget.BudgetExhaustedError):
        await budget.reserve_llm_calls("report", settings=Settings(llm_daily_budget=500))
    assert sent[0][0][0] == "INCRBY" and sent[0][0][1].startswith("llm_budget:")

    down = redis_mod.UpstashRedis(
        "https://r.io",
        "t",
        httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))),
    )
    monkeypatch.setattr(budget, "get_redis", lambda: down)
    await budget.reserve_llm_calls("report", settings=Settings(llm_daily_budget=500))  # local: 1


def test_exhausted_budget_is_a_json_503_before_any_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, llm = FakeDB(), FakeLLM()
    install(monkeypatch, db, llm)
    monkeypatch.setattr(budget, "get_settings", lambda: Settings(llm_daily_budget=1))
    client = TestClient(app)
    s = client.post("/api/v1/sessions?demo=true", json={"consent": True}).json()
    r = client.post(
        f"/api/v1/sessions/{s['session_id']}/analyze", headers={"X-Guest-Token": s["guest_token"]}
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "daily_budget_exhausted"
    assert int(r.headers["retry-after"]) > 0
    assert llm.calls == []


def test_demo_cache_serves_the_analysis_without_llm_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    db, llm = FakeDB(), FakeLLM()
    install(monkeypatch, db, llm)
    monkeypatch.setattr(budget, "get_settings", lambda: Settings(llm_daily_budget=1))  # exhausted
    db.demo_cache = {
        "match_score": 64,
        "breakdown": {
            "role_title": "Junior AI Engineer",
            "formula": "f",
            **{
                k: {"weight": 0.1, "score": 0.5, "detail": "d"}
                for k in ("must_have", "nice_to_have", "seniority_fit")
            },
        },
        "gaps": [],
        "strengths": [],
        "likely_questions": [],
        "prep_plan": [],
    }
    client = TestClient(app)
    s = client.post("/api/v1/sessions?demo=true", json={"consent": True}).json()
    r = client.post(
        f"/api/v1/sessions/{s['session_id']}/analyze", headers={"X-Guest-Token": s["guest_token"]}
    )
    events = dict(sse_events(r.text))
    assert events["done"]["match_score"] == 64
    assert llm.calls == [] and "copy_demo_analysis" in db.rpc_calls


# ------------------------------------------------------------------ opt-ins and startup config


def test_reminder_opt_in_needs_an_email(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDB()
    install(monkeypatch, db, FakeLLM())
    client = TestClient(app)
    client.post("/api/v1/sessions", json={"consent": True, "reminders_opt_in": True})
    client.post(
        "/api/v1/sessions",
        json={"consent": True, "email": "a@b.co", "reminders_opt_in": True, "email_opt_in": False},
    )
    rows = db.rows("sessions")
    assert "reminders_opt_in" not in rows[0]  # unticked/no email: column not even sent
    assert rows[1]["reminders_opt_in"] is True and rows[1]["email_opt_in"] is False


def test_startup_fails_fast_in_production_only() -> None:
    broken = Settings(app_env="production", outbound_webhook_url="http://n8n.example/hook")
    errors, warnings = broken.startup_problems()
    assert any("OUTBOUND_WEBHOOK_SECRET" in e for e in errors)
    assert any("https" in e for e in errors) and any("CRON_SECRET" in w for w in warnings)
    with pytest.raises(RuntimeError):
        check_startup(broken)
    check_startup(Settings(app_env="development"))  # only logs
    good = Settings(
        app_env="production",
        supabase_url="https://x.supabase.co",
        supabase_service_role_key="k",
        groq_api_key="g",
    )
    check_startup(good)
