"""Phase 7 reminders: double opt-in, one-click unsubscribe, pause/stop rules, idempotent sends."""

import re
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.routers.reminders as reminders_router
from app.core.rate_limit import POLICIES
from app.main import app
from app.services import reminders as svc
from tests.fakes import FakeDB
from tests.phase7_helpers import SECRETS, RecordingEmail, env, plan, report

TODAY = date(2026, 11, 12)


@pytest.fixture(name="cfg")
def cfg_fixture(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    with env(monkeypatch, **SECRETS) as s:
        yield s


async def _pending(db: FakeDB, mail: RecordingEmail, email: str = "ali@example.com") -> str:
    result = await svc.subscribe(
        db, mail, session_id="s1", email=email, role_title="Junior AI Engineer", plan=plan()
    )
    assert result == "created"
    return re.search(r"/reminders/([A-Za-z0-9_-]{43})", mail.sent[-1]["text"]).group(1)  # type: ignore[union-attr]


def _row(db: FakeDB) -> dict[str, Any]:
    return db.rows("reminders")[0]


async def test_subscribe_is_pending_until_confirmed(cfg) -> None:  # type: ignore[no-untyped-def]
    db, mail = FakeDB(), RecordingEmail()
    token = await _pending(db, mail)
    row = _row(db)
    assert row["status"] == "pending" and row["day_index"] == 0
    assert token not in str(row) and row["token_hash"] == svc.hash_token(token)  # only the hash
    assert len(row["plan"]) == 7 and len(row["plan"][0]["tasks"]) == 2  # trimmed
    assert row["plan"][0]["resource_urls"] == []  # non-allowlisted link dropped
    confirm = mail.sent[0]
    assert confirm["kind"] == "reminder_confirm" and "Confirm" in confirm["subject"]
    assert "Day 1" not in confirm["text"]  # nothing but the confirmation before the click
    # Same session again: no second row, no second email.
    again = await svc.subscribe(
        db, mail, session_id="s1", email="x@y.co", role_title="r", plan=plan()
    )
    assert again == "exists" and len(mail.sent) == 1


async def test_per_recipient_limit_blocks_list_bombing(cfg) -> None:  # type: ignore[no-untyped-def]
    db, mail = FakeDB(), RecordingEmail()
    limit = POLICIES["email_recipient"].limit
    results = [
        await svc.subscribe(
            db, mail, session_id=f"s{i}", email="Victim@Example.com ", role_title="r", plan=plan()
        )
        for i in range(limit + 1)
    ]
    assert results[:limit] == ["created"] * limit and results[limit] == "limited"


async def test_disabled_and_no_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    db, mail = FakeDB(), RecordingEmail()
    with env(monkeypatch, RESEND_API_KEY="re_x", EMAIL_FROM="a@b.co"):  # no token secret
        assert (
            await svc.subscribe(
                db, mail, session_id="s", email="a@b.co", role_title="r", plan=plan()
            )
            == "disabled"
        )
    with env(monkeypatch, **SECRETS):
        assert (
            await svc.subscribe(
                db, mail, session_id="s", email="a@b.co", role_title="r", plan=plan(3)
            )
            == "no_plan"
        )
    assert mail.sent == []


async def test_failed_confirmation_email_leaves_no_row(cfg) -> None:  # type: ignore[no-untyped-def]
    db = FakeDB()
    with pytest.raises(svc.EmailError):
        await svc.subscribe(
            db,
            RecordingEmail(fail=True),
            session_id="s",
            email="a@b.co",
            role_title="r",
            plan=plan(),
        )
    assert db.rows("reminders") == []


async def test_confirm_sends_day_one_with_one_click_unsubscribe(cfg) -> None:  # type: ignore[no-untyped-def]
    db, mail = FakeDB(), RecordingEmail()
    token = await _pending(db, mail)
    row = await svc.find_by_token(db, token)
    assert row is not None
    status = await svc.confirm(db, mail, row)
    assert status["status"] == "active" and status["day_index"] == 1
    day1 = mail.sent[-1]
    assert day1["subject"] == "Day 1/7 · Junior AI Engineer: Focus 1"
    assert day1["headers"] == {
        "List-Unsubscribe": f"<https://hireready.example/api/v1/unsubscribe/{token}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    assert f"https://hireready.example/unsubscribe/{token}" in day1["html"]  # visible link too
    assert "<img" not in day1["html"]  # no tracking pixel
    assert len(day1["text"].split()) < 140  # short: one task a day
    # A second click (or a mail scanner) changes nothing and sends nothing.
    await svc.confirm(db, mail, (await svc.find_by_token(db, token)) or {})
    assert len(mail.sent) == 2


async def _active(db: FakeDB, mail: RecordingEmail) -> str:
    token = await _pending(db, mail)
    await svc.confirm(db, mail, (await svc.find_by_token(db, token)) or {})
    return token


async def test_cron_retry_never_double_sends(cfg) -> None:  # type: ignore[no-untyped-def]
    db, mail = FakeDB(), RecordingEmail()
    await _active(db, mail)
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    _row(db)["next_send_date"] = tomorrow
    first = await svc.send_due(db, mail, today=TODAY + timedelta(days=1))
    retry = await svc.send_due(db, mail, today=TODAY + timedelta(days=1))
    assert first["sent"] == 1 and retry["due"] == 0
    assert [m["subject"][:7] for m in mail.sent[2:]] == ["Day 2/7"]


async def test_pause_after_three_unclicked_days_and_resume(cfg) -> None:  # type: ignore[no-untyped-def]
    db, mail = FakeDB(), RecordingEmail()
    token = await _active(db, mail)  # day 1 sent on confirm
    for _ in range(3):  # days 2 and 3, then the pause instead of day 4
        _row(db)["next_send_date"] = TODAY.isoformat()
        await svc.send_due(db, mail, today=TODAY)
    kinds = [m["kind"] for m in mail.sent]
    assert kinds == ["reminder_confirm", "reminder", "reminder", "reminder", "reminder_paused"]
    assert _row(db)["status"] == "paused"
    _row(db)["next_send_date"] = TODAY.isoformat()
    assert (await svc.send_due(db, mail, today=TODAY))["due"] == 0  # paused: nothing goes out
    resumed = await svc.resume(db, (await svc.find_by_token(db, token)) or {})
    assert resumed["status"] == "active" and resumed["last_click_day"] == 3


async def test_mark_done_keeps_the_plan_going_and_it_stops_after_day_7(cfg) -> None:  # type: ignore[no-untyped-def]
    db, mail = FakeDB(), RecordingEmail()
    token = await _active(db, mail)
    for _ in range(8):
        row = (await svc.find_by_token(db, token)) or {}
        await svc.mark_done(db, row, int(row["day_index"]))
        _row(db)["next_send_date"] = TODAY.isoformat()
        await svc.send_due(db, mail, today=TODAY)
    days = [m["subject"][:7] for m in mail.sent if m["kind"] == "reminder"]
    assert days == [f"Day {n}/7" for n in range(1, 8)]
    assert _row(db)["status"] == "finished" and "practise again" in mail.sent[-1]["html"]
    assert (await svc.send_due(db, mail, today=TODAY))["due"] == 0  # sequence ends on its own


async def test_email_failure_gives_the_day_back(cfg) -> None:  # type: ignore[no-untyped-def]
    db, mail = FakeDB(), RecordingEmail()
    await _active(db, mail)
    _row(db)["next_send_date"] = TODAY.isoformat()
    stats = await svc.send_due(db, RecordingEmail(fail=True), today=TODAY)
    assert stats["failed"] == 1 and _row(db)["day_index"] == 1  # retried tomorrow


async def test_daily_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    with env(monkeypatch, **SECRETS, REMINDER_DAILY_CAP="2"):
        db, mail = FakeDB(), RecordingEmail()
        for i in range(3):
            await svc.subscribe(
                db, mail, session_id=f"s{i}", email=f"u{i}@x.co", role_title="r", plan=plan()
            )
        for r in db.rows("reminders"):
            r.update(status="active", next_send_date=TODAY.isoformat(), confirmed_at="2026-11-11")
        stats = await svc.send_due(db, mail, today=TODAY)
    assert stats["sent"] == 2 and stats["capped"] == 1


# ------------------------------------------------------------------ public endpoints


@pytest.fixture(name="api")
def api_fixture(cfg, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    db, mail = FakeDB(), RecordingEmail()
    monkeypatch.setattr(reminders_router, "get_db", lambda: db)
    monkeypatch.setattr(reminders_router.email_service, "get_email_provider", lambda: mail)
    return TestClient(app), db, mail


async def test_token_endpoints(api) -> None:  # type: ignore[no-untyped-def]
    client, db, mail = api
    token = await _pending(db, mail)
    status = client.get(f"/api/v1/reminders/{token}")
    assert status.status_code == 200 and status.json()["status"] == "pending"
    assert "email" not in status.text and "ali@" not in status.text
    assert status.headers["x-robots-tag"].startswith("noindex")
    assert client.post(f"/api/v1/reminders/{token}/confirm").json()["day"] == 1
    assert (
        client.post(f"/api/v1/reminders/{token}/done", json={"day": 1}).json()["last_done_day"] == 1
    )
    assert client.post(f"/api/v1/reminders/{token}/done", json={"day": 9}).status_code == 422
    # GET of the unsubscribe URL must not unsubscribe (RFC 8058; mail scanners prefetch links).
    assert client.get(f"/api/v1/unsubscribe/{token}").json() == {"subscribed": True}
    assert db.rows("reminders")
    one_click = client.post(
        f"/api/v1/unsubscribe/{token}",
        content="List-Unsubscribe=One-Click",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert one_click.status_code == 200 and db.rows("reminders") == []  # deleted at once
    assert client.post(f"/api/v1/unsubscribe/{token}").status_code == 200  # idempotent
    assert client.get(f"/api/v1/reminders/{token}").status_code == 404
    assert client.get("/api/v1/reminders/not-a-token").status_code == 404


def test_session_opt_in_endpoint(api, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    client, db, mail = api
    import app.routers.sessions as sessions_router

    monkeypatch.setattr(sessions_router, "get_db", lambda: db)
    s = client.post("/api/v1/sessions", json={"consent": True, "email": "ali@example.com"}).json()
    sid, h = s["session_id"], {"X-Guest-Token": s["guest_token"]}
    assert (
        client.post(f"/api/v1/sessions/{sid}/reminders", headers=h).status_code == 409
    )  # no report
    db.rows("reports").append({"session_id": sid, "report": report().model_dump(mode="json")})
    r = client.post(f"/api/v1/sessions/{sid}/reminders", headers=h)
    assert r.json() == {"status": "pending"} and mail.sent[-1]["kind"] == "reminder_confirm"
    assert client.post(f"/api/v1/sessions/{sid}/reminders", headers=h).json() == {
        "status": "exists"
    }
    assert client.post(f"/api/v1/sessions/{sid}/reminders").status_code == 404  # no guest token
