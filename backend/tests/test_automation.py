"""Phase 7: cron auth + jobs, the Standard Webhooks signature, and post-report automation."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import app.routers.cron as cron_router
from app.core.config import Settings
from app.core.sse import Event
from app.main import app
from app.services import automation, webhook
from tests.fakes import FakeDB
from tests.phase7_helpers import SECRETS, RecordingEmail, env, report

AUTH = {"Authorization": "Bearer cron-test-secret"}
SID = "6f1c2b9e-3d4a-4e5f-8a7b-1c2d3e4f5a6b"


# ------------------------------------------------------------------ cron


class CleanupDB(FakeDB):
    """Two batches of expired sessions, then nothing left."""

    def __init__(self) -> None:
        super().__init__()
        self.batches = [
            {"sessions": 200, "answers": 900, "reminders": 1, "more": True},
            {"sessions": 12, "answers": 30, "reminders": 0, "more": False},
        ]

    async def rpc(self, fn: str, args: dict[str, Any]) -> Any:
        assert fn == "cleanup_expired" and args == {"p_batch": 200}
        return self.batches.pop(0) if self.batches else {"sessions": 0, "more": False}


def test_cron_endpoints_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    with env(monkeypatch, CRON_SECRET=""):
        monkeypatch.delenv("CRON_SECRET")
        r = client.get("/api/v1/cron/cleanup", headers=AUTH)
        assert r.status_code == 503 and r.json()["error"]["code"] == "cron_not_configured"
    with env(monkeypatch, CRON_SECRET="cron-test-secret"):
        for headers in (
            {},
            {"Authorization": "Bearer wrong"},
            {"Authorization": "cron-test-secret"},
        ):
            assert client.get("/api/v1/cron/cleanup", headers=headers).status_code == 401
            assert client.get("/api/v1/cron/reminders", headers=headers).status_code == 401


def test_cleanup_runs_batches_until_done(monkeypatch: pytest.MonkeyPatch) -> None:
    db = CleanupDB()
    monkeypatch.setattr(cron_router, "get_db", lambda: db)
    with env(monkeypatch, CRON_SECRET="cron-test-secret"):
        body = TestClient(app).get("/api/v1/cron/cleanup", headers=AUTH).json()
    assert body == {
        "ok": True,
        "batches": 2,
        "more": False,
        "deleted": {"sessions": 212, "answers": 930, "reminders": 1},
    }


def test_reminder_cron_is_a_clean_noop_without_email(monkeypatch: pytest.MonkeyPatch) -> None:
    with env(monkeypatch, CRON_SECRET="cron-test-secret"):
        body = TestClient(app).get("/api/v1/cron/reminders", headers=AUTH).json()
    assert body == {"ok": True, "enabled": False}


def test_reminder_cron_sends_and_records(monkeypatch: pytest.MonkeyPatch) -> None:
    db, mail = FakeDB(), RecordingEmail()
    monkeypatch.setattr(cron_router, "get_db", lambda: db)
    monkeypatch.setattr(cron_router.email_service, "get_email_provider", lambda: mail)
    with env(monkeypatch, **SECRETS):
        body = TestClient(app).get("/api/v1/cron/reminders", headers=AUTH).json()
    assert body["enabled"] is True and body["due"] == 0
    assert db.rows("cron_runs")[0]["name"] == "reminders"


def test_cron_status_is_public_and_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDB()
    db.rows("cron_runs").append(
        {"name": "cleanup", "ran_at": "2026-11-12T02:00:00+00:00", "stats": {"sessions": 4}}
    )
    monkeypatch.setattr(cron_router, "get_db", lambda: db)
    body = TestClient(app).get("/api/v1/cron/status").json()
    assert body == {
        "last_runs": {
            "cleanup": {
                "ran_at": "2026-11-12T02:00:00+00:00",
                "sessions_deleted": 4,
                "emails_sent": None,
            }
        }
    }


# ------------------------------------------------------------------ webhook


def test_signature_matches_the_standard_webhooks_spec() -> None:
    # Test vector from the Standard Webhooks reference libraries.
    secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
    body = b'{"test": 2432232314}'
    sig = webhook.sign(secret, "msg_p5jXN8AQM9LWM0D4loKWxJek", 1614265330, body)
    assert sig == "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="


def test_verify_rejects_tampering_replays_and_accepts_rotation() -> None:
    body = b'{"type":"report.completed"}'
    h = {"webhook-id": "msg_1", "webhook-timestamp": "1000", "webhook-signature": ""}
    h["webhook-signature"] = "v1,old " + webhook.sign("new-secret", "msg_1", 1000, body)
    assert webhook.verify("new-secret", h, body, now=1100)  # one of several signatures matches
    assert not webhook.verify("new-secret", h, body + b" ", now=1100)
    assert not webhook.verify("new-secret", h, body, now=1000 + 301)  # outside +-5 min
    assert not webhook.verify("other", h, body, now=1100)


async def test_deliver_signs_retries_and_never_leaks_cv_text() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(500 if len(seen) == 1 else 204)

    async def no_sleep(_: float) -> None:
        return None

    s = Settings(outbound_webhook_url="https://n8n.example/h", outbound_webhook_secret="sek")
    payload = webhook.report_completed_payload("sid-1", report())
    status = await webhook.deliver(
        payload, settings=s, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=no_sleep,
    )  # fmt: skip
    assert status == 204 and len(seen) == 2
    assert seen[0].headers["webhook-id"] == seen[1].headers["webhook-id"]  # stable across retries
    last = seen[-1]
    assert webhook.verify("sek", dict(last.headers), last.content)
    data = json.loads(last.content)
    assert data["type"] == "report.completed" and data["data"]["readiness_score"] == 68
    assert set(data["data"]) == {
        "session_id", "role_title", "readiness_score", "band", "band_label", "questions",
        "generated_at",
    }  # fmt: skip


async def test_deliver_is_off_or_swallows_errors() -> None:
    assert await webhook.deliver({}, settings=Settings()) is None

    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async def no_sleep(_: float) -> None:
        return None

    s = Settings(outbound_webhook_url="https://n8n.example/h", outbound_webhook_secret="sek")
    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    assert await webhook.deliver({}, settings=s, client=client, sleep=no_sleep) is None


# ------------------------------------------------------------------ after the report


async def _stream(events: list[Event]) -> AsyncIterator[Event]:
    for e in events:
        yield e


async def test_automation_runs_after_done_and_cannot_break_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, mail = FakeDB(), RecordingEmail()
    db.rows("sessions").append(
        {"id": SID, "email": "ali@example.com", "email_opt_in": True, "reminders_opt_in": True}
    )
    db.rows("reports").append({"session_id": SID, "report": {}})
    monkeypatch.setattr(automation.email_service, "get_email_provider", lambda: mail)

    async def broken_webhook(*_: Any, **__: Any) -> None:
        raise RuntimeError("receiver down")

    monkeypatch.setattr(automation.webhook, "deliver", broken_webhook)
    done = report().model_dump(mode="json")
    with env(monkeypatch, **SECRETS):
        out = [
            e
            async for e in automation.after_report(
                _stream([("status", {}), ("done", done)]), db, {"id": SID}
            )
        ]
    assert [e for e, _ in out] == ["status", "done"]
    kinds = sorted(m.get("kind", "report") for m in mail.sent)
    assert kinds == ["reminder_confirm", "report"]  # both opt-ins honoured, separately
    assert db.rows("reports")[0]["emailed_at"]
    assert db.rows("reminders")[0]["status"] == "pending"


async def test_no_opt_in_means_no_email(monkeypatch: pytest.MonkeyPatch) -> None:
    db, mail = FakeDB(), RecordingEmail()
    db.rows("sessions").append({"id": SID, "email": "ali@example.com"})
    monkeypatch.setattr(automation.email_service, "get_email_provider", lambda: mail)
    with env(monkeypatch, **SECRETS):
        await automation.on_report_completed(db, {"id": SID}, report())
    await asyncio.sleep(0)
    assert mail.sent == [] and db.rows("reminders") == []
