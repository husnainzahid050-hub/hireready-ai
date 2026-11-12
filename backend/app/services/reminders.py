"""Daily prep-plan reminder emails (SPEC 6.7), designed from the Phase 7 research brief.

Lifecycle of one `reminders` row (migration 20261112000007):

    pending --confirm click--> active --day 7 sent--> finished --3 days--> deleted by cleanup
       |                          |  \\--3 sent days without a "Mark done" click--> paused
       '--3 days, no click--> deleted        (one kind "paused" email; "Restart" -> active)
    any state --unsubscribe--> deleted (immediately, row and all)

Rules this module enforces:
- Separate opt-in from the report email (`sessions.reminders_opt_in`), and DOUBLE opt-in: the first
  email only asks to confirm. Nothing else is sent until the person clicks, so the form can't be
  used to put someone else on a mailing list. Confirmation emails count toward the per-recipient
  limit (3 per address per day, across all sessions).
- The row has its own lifetime: it holds only the email, job title, the 7 plan days and a hashed
  token, and the session cleanup detaches it instead of deleting it (the plan outlives the 7-day
  guest expiry).
- One single-purpose token per row: token = HMAC-SHA256(REMINDER_TOKEN_SECRET, nonce), only its
  SHA-256 is stored. It can confirm, mark a day done, restart or unsubscribe; it never opens the
  report or the session.
- RFC 8058 one-click unsubscribe: `List-Unsubscribe: <https://.../api/v1/unsubscribe/{token}>` and
  `List-Unsubscribe-Post: List-Unsubscribe=One-Click`, plus a visible footer link.
- One concrete task per day, a job-named subject ("Day 3/7 · Junior AI Engineer: SQL joins"),
  progress dots, no tracking pixels or click-tracking redirects (links point straight at our pages;
  Resend's open/click tracking must stay OFF for the sending domain), stop after day 7, pause after
  3 unclicked days. Calm tone: no streak guilt, no fake urgency.
- Sends are idempotent: the day counter moves with a compare-and-swap BEFORE the email goes out
  (a retried cron can't double-send), and Resend's Idempotency-Key backs that up.
"""

import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import UTC, date, datetime, timedelta
from html import escape
from typing import Any, Literal

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.rate_limit import allow
from app.core.security import hash_token
from app.db.client import SupabaseRest
from app.schemas.analysis import PrepDay
from app.services.catalog import allowed_urls
from app.services.email import EmailError, EmailProvider, email_configured

log = get_logger(__name__)

DAYS = 7
PAUSE_AFTER_UNCLICKED = 3
PENDING_TTL = timedelta(days=3)
KEEP_AFTER_LAST_SEND = timedelta(days=3)
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")  # base64url of 32 bytes, no padding
COLUMNS = (
    "id,session_id,email,role_title,plan,status,day_index,last_click_day,"
    "next_send_date,confirmed_at,expires_at"
)
COLUMNS_WITH_NONCE = COLUMNS + ",token_nonce"  # only for code that builds links (never returned)

SubscribeResult = Literal["created", "exists", "limited", "disabled", "no_plan"]
SendResult = Literal["sent", "paused", "finished", "skipped", "failed"]


def reminders_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return email_configured(s) and bool(s.reminder_token_secret)


def _secret(settings: Settings | None = None) -> bytes:
    s = settings or get_settings()
    if not s.reminder_token_secret:
        raise RuntimeError("REMINDER_TOKEN_SECRET is not set")
    return s.reminder_token_secret.get_secret_value().encode()


def make_token(nonce: str, settings: Settings | None = None) -> str:
    digest = hmac.new(_secret(settings), f"reminder:{nonce}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def email_hash(address: str) -> str:
    return hash_token(address.strip().lower())


def _now() -> datetime:
    return datetime.now(UTC)


def today_utc() -> date:
    return _now().date()


# ------------------------------------------------------------------ rows


def plan_for_email(days: list[PrepDay]) -> list[dict[str, Any]]:
    """Keep only what an email needs: focus, at most 2 tasks, at most 1 allowlisted link."""
    ok = allowed_urls()
    return [
        {
            "day": i + 1,
            "focus": d.focus[:120],
            "tasks": [t[:240] for t in d.tasks[:2]],
            "resource_urls": [u for u in d.resource_urls if u in ok][:1],
        }
        for i, d in enumerate(days[:DAYS])
    ]


async def find_by_token(db: SupabaseRest, token: str) -> dict[str, Any] | None:
    if not TOKEN_RE.fullmatch(token):
        return None
    rows = await db.select(
        "reminders", {"select": COLUMNS, "token_hash": f"eq.{hash_token(token)}", "limit": "1"}
    )
    if not rows:
        return None
    row = rows[0]
    if datetime.fromisoformat(str(row["expires_at"])) < _now():
        return None
    return row


def public_status(row: dict[str, Any]) -> dict[str, Any]:
    """What a token link may show: no email, no session id."""
    return {
        "status": row["status"],
        "day": row["day_index"],
        "days_total": DAYS,
        "last_done_day": row["last_click_day"],
        "role_title": row["role_title"],
        "plan": [{"day": d["day"], "focus": d["focus"]} for d in row["plan"]],
    }


async def _cas(
    db: SupabaseRest, row: dict[str, Any], expect: dict[str, str], values: dict[str, Any]
) -> dict[str, Any] | None:
    """Update the row only if it still matches `expect`; None = someone else changed it first."""
    changed = await db.update_returning(
        "reminders", {"id": f"eq.{row['id']}", **expect}, values, select=COLUMNS
    )
    return changed[0] if changed else None


# ------------------------------------------------------------------ links + rendering


def links(token: str, settings: Settings | None = None) -> dict[str, str]:
    base = (settings or get_settings()).app_base_url.rstrip("/")
    return {
        "page": f"{base}/reminders/{token}",
        "unsubscribe_page": f"{base}/unsubscribe/{token}",
        "one_click": f"{base}/api/v1/unsubscribe/{token}",
        "start": f"{base}/start",
        "privacy": f"{base}/privacy#reminders",
    }


def unsubscribe_headers(link: dict[str, str]) -> dict[str, str]:
    return {
        "List-Unsubscribe": f"<{link['one_click']}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


_WRAP = (
    "<div style='font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:560px;"
    "line-height:1.5;color:#111'>"
)
_MUTED = "color:#555;font-size:13px"


def _button(href: str, label: str) -> str:
    return (
        f'<p><a href="{escape(href, quote=True)}" style="display:inline-block;padding:10px 16px;'
        'background:#4f46e5;color:#fff;border-radius:8px;text-decoration:none">'
        f"{escape(label)}</a></p>"
    )


def _link(href: str, label: str) -> str:
    return f'<a href="{escape(href, quote=True)}">{escape(label)}</a>'


def _role(row: dict[str, Any]) -> str:
    return str(row.get("role_title") or "your interview")


def _footer(row: dict[str, Any], link: dict[str, str]) -> tuple[str, str]:
    since = str(row.get("confirmed_at") or "")[:10]
    why = (
        f"You're getting this because you asked for 7 daily prep emails for {_role(row)}"
        + (f" (confirmed {since})" if since else "")
        + ". They stop on their own after day 7."
    )
    html = (
        f"<p style='{_MUTED}'>{escape(why)}<br>"
        f"{_link(link['unsubscribe_page'], 'Unsubscribe (one click)')} &middot; "
        f"{_link(link['privacy'], 'Why am I getting this?')}</p>"
    )
    text = f"{why}\nUnsubscribe: {link['unsubscribe_page']}\n"
    return html, text


def dots(done: int) -> str:
    return " ".join("●" if i < done else "○" for i in range(DAYS))


def render_confirmation(role: str, link: dict[str, str]) -> tuple[str, str, str]:
    subject = f"Confirm your 7-day prep plan: {role}"[:150]
    lead = (
        "Someone (hopefully you) asked HireReady AI to send 7 short daily prep emails to this "
        f"address, one task a day for your {role} interview. Nothing is sent until you confirm."
    )
    ignore = (
        "Not you? Ignore this email. We won't email this address again for this request, and it "
        "is deleted in 3 days."
    )
    html = (
        _WRAP
        + f"<h2>Start your 7-day plan?</h2><p>{escape(lead)}</p>"
        + _button(link["page"], "Start my 7-day plan")
        + f"<p style='{_MUTED}'>{escape(ignore)}</p></div>"
    )
    text = f"{lead}\n\nStart my 7-day plan: {link['page']}\n\n{ignore}\n"
    return subject, html, text


def render_day(row: dict[str, Any], n: int, link: dict[str, str]) -> tuple[str, str, str]:
    day = row["plan"][n - 1]
    focus, tasks, urls = str(day["focus"]), list(day.get("tasks") or []), day.get("resource_urls")
    subject = f"Day {n}/{DAYS} · {_role(row)}: {focus}"[:150]
    last = n == DAYS
    foot_html, foot_text = _footer(row, link)
    html = (
        _WRAP
        + f"<p style='{_MUTED}'>Day {n} of {DAYS} &middot; {escape(_role(row))}</p>"
        + f"<h2 style='margin-top:4px'>Today's focus: {escape(focus)}</h2>"
        + "<p>Do this (15-20 minutes):</p><ol>"
        + "".join(f"<li>{escape(t)}</li>" for t in tasks)
        + "</ol>"
        + (f"<p>Read: {_link(urls[0], urls[0])}</p>" if urls else "")
        + _button(f"{link['page']}?day={n}", "Mark today done")
        + (
            "<p><strong>That's the whole plan.</strong> Take a fresh mock interview to see how "
            f"far you've moved: {_link(link['start'], 'practise again')}.</p>"
            if last
            else ""
        )
        + f"<p style='letter-spacing:2px'>{dots(n)}</p>"
        + foot_html
        + "</div>"
    )
    text = (
        f"Day {n} of {DAYS} - {_role(row)}\nToday's focus: {focus}\n\nDo this (15-20 minutes):\n"
        + "".join(f"{i}. {t}\n" for i, t in enumerate(tasks, 1))
        + (f"Read: {urls[0]}\n" if urls else "")
        + f"\nMark today done: {link['page']}?day={n}\n"
        + (f"\nThat's the whole plan. Practise again: {link['start']}\n" if last else "")
        + f"\nProgress: {dots(n)}\n\n"
        + foot_text
    )
    return subject, html, text


def render_paused(row: dict[str, Any], link: dict[str, str]) -> tuple[str, str, str]:
    subject = f"We've paused your prep emails: {_role(row)}"[:150]
    lead = (
        "You haven't marked a day done for a few days, so we've paused your prep emails. "
        "No more will arrive unless you restart. Job hunting is busy; the plan will be here."
    )
    foot_html, foot_text = _footer(row, link)
    html = (
        _WRAP
        + f"<h2>Prep emails paused</h2><p>{escape(lead)}</p>"
        + _button(link["page"], "Restart my plan")
        + foot_html
        + "</div>"
    )
    text = f"{lead}\n\nRestart my plan: {link['page']}\n\n{foot_text}"
    return subject, html, text


# ------------------------------------------------------------------ actions


async def subscribe(
    db: SupabaseRest,
    provider: EmailProvider,
    *,
    session_id: str,
    email: str,
    role_title: str,
    plan: list[PrepDay],
    settings: Settings | None = None,
) -> SubscribeResult:
    """Create a PENDING reminder and send the confirmation email (double opt-in)."""
    s = settings or get_settings()
    if not reminders_configured(s):
        return "disabled"
    if len(plan) < DAYS:
        return "no_plan"
    existing = await db.select(
        "reminders", {"select": "id", "session_id": f"eq.{session_id}", "limit": "1"}
    )
    if existing:
        return "exists"
    e_hash = email_hash(email)
    if not await allow("email_recipient", subject=e_hash[:32]):
        return "limited"
    nonce = secrets.token_urlsafe(24)
    token = make_token(nonce, s)
    row = await db.insert_returning(
        "reminders",
        {
            "session_id": session_id,
            "email": email.strip(),
            "email_hash": e_hash,
            "role_title": role_title[:200],
            "plan": plan_for_email(plan),
            "token_nonce": nonce,
            "token_hash": hash_token(token),
            "status": "pending",
            "expires_at": (_now() + PENDING_TTL).isoformat(),
        },
    )
    subject, html, text = render_confirmation(role_title or "your interview", links(token, s))
    try:
        await provider.send(
            to=email.strip(),
            subject=subject,
            html=html,
            text=text,
            idempotency_key=f"reminder-confirm/{row['id']}",
            kind="reminder_confirm",
        )
    except EmailError:
        await db.delete("reminders", {"id": f"eq.{row['id']}"})
        raise
    log.info("reminder_pending", extra={"extra_fields": {"session_id": session_id}})
    return "created"


def _nonce(row: dict[str, Any]) -> str:
    nonce = row.get("token_nonce")
    if not nonce:
        raise KeyError("token_nonce")  # the row must be selected with COLUMNS_WITH_NONCE
    return str(nonce)


def _expiry_after(day_sent: int) -> str:
    remaining = timedelta(days=DAYS - day_sent)
    return (_now() + remaining + KEEP_AFTER_LAST_SEND).isoformat()


async def send_day(
    db: SupabaseRest,
    provider: EmailProvider,
    row: dict[str, Any],
    today: date,
    settings: Settings | None = None,
) -> SendResult:
    """Send the next day (or the pause email) for one ACTIVE row. Never sends twice."""
    s = settings or get_settings()
    n = int(row["day_index"])
    expect = {"status": "eq.active", "day_index": f"eq.{n}"}
    token = make_token(_nonce(row), s)
    link = links(token, s)
    if n >= DAYS or n >= len(row["plan"]):
        await _cas(db, row, expect, {"status": "finished", "next_send_date": None})
        return "finished"
    if n > 0 and n - int(row["last_click_day"]) >= PAUSE_AFTER_UNCLICKED:
        if await _cas(db, row, expect, {"status": "paused", "next_send_date": None}) is None:
            return "skipped"
        subject, html, text = render_paused(row, link)
        kind, key = "reminder_paused", f"reminder/{row['id']}/paused/{n}"
        result: SendResult = "paused"
    else:
        nxt = n + 1
        claimed = await _cas(
            db,
            row,
            expect,
            {
                "day_index": nxt,
                "status": "finished" if nxt == DAYS else "active",
                "next_send_date": None if nxt == DAYS else (today + timedelta(days=1)).isoformat(),
                "last_sent_at": _now().isoformat(),
                "expires_at": _expiry_after(nxt),
            },
        )
        if claimed is None:  # another run (a cron retry) took this day first
            return "skipped"
        subject, html, text = render_day(row, nxt, link)
        kind, key = "reminder", f"reminder/{row['id']}/day{nxt}"
        result = "sent"
    try:
        await provider.send(
            to=row["email"],
            subject=subject,
            html=html,
            text=text,
            idempotency_key=key,
            headers=unsubscribe_headers(link),
            kind=kind,
        )
    except EmailError:
        # Give the day back so tomorrow's run retries it.
        await db.update(
            "reminders",
            {"id": f"eq.{row['id']}"},
            {"day_index": n, "status": "active", "next_send_date": today.isoformat()},
        )
        return "failed"
    return result


async def confirm(
    db: SupabaseRest,
    provider: EmailProvider | None,
    row: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """pending -> active, and Day 1 goes out right away (the click proves the address)."""
    if row["status"] != "pending":
        return row  # idempotent: a second click (or a mail scanner) changes nothing
    today = today_utc()
    active = await _cas(
        db,
        row,
        {"status": "eq.pending"},
        {
            "status": "active",
            "confirmed_at": _now().isoformat(),
            "day_index": 0,
            "last_click_day": 0,
            "next_send_date": today.isoformat(),
            "expires_at": _expiry_after(0),
        },
    )
    if active is None:
        return row
    log.info("reminder_confirmed", extra={"extra_fields": {"reminder_id": row["id"]}})
    if provider is not None:
        full = await db.select(
            "reminders", {"select": COLUMNS_WITH_NONCE, "id": f"eq.{row['id']}", "limit": "1"}
        )
        if full:
            await send_day(db, provider, full[0], today, settings)
    refreshed = await db.select(
        "reminders", {"select": COLUMNS, "id": f"eq.{row['id']}", "limit": "1"}
    )
    return refreshed[0] if refreshed else active


async def mark_done(db: SupabaseRest, row: dict[str, Any], day: int) -> dict[str, Any]:
    """Record engagement (no tracking pixel needed): resets the 'unclicked days' count."""
    if row["status"] not in ("active", "finished") or not 1 <= day <= int(row["day_index"]):
        return row
    if day <= int(row["last_click_day"]):
        return row
    updated = await _cas(db, row, {}, {"last_click_day": day})
    return updated or row


async def resume(db: SupabaseRest, row: dict[str, Any]) -> dict[str, Any]:
    if row["status"] != "paused":
        return row
    n = int(row["day_index"])
    updated = await _cas(
        db,
        row,
        {"status": "eq.paused"},
        {
            "status": "active",
            "last_click_day": n,
            "next_send_date": (today_utc() + timedelta(days=1)).isoformat(),
            "expires_at": _expiry_after(n),
        },
    )
    return updated or row


async def unsubscribe(db: SupabaseRest, token: str) -> None:
    """Delete the row at once (nothing kept). Idempotent: unknown tokens are a no-op."""
    if TOKEN_RE.fullmatch(token):
        await db.delete("reminders", {"token_hash": f"eq.{hash_token(token)}"})
        log.info("reminder_unsubscribed")


async def send_due(
    db: SupabaseRest,
    provider: EmailProvider,
    *,
    settings: Settings | None = None,
    today: date | None = None,
    budget_s: float = 45.0,
) -> dict[str, int]:
    """The daily cron: one email per due ACTIVE row, oldest first, up to REMINDER_DAILY_CAP
    (below the email provider's daily free quota), and inside a time budget."""
    s = settings or get_settings()
    day = today or today_utc()
    deadline = time.monotonic() + budget_s
    rows = await db.select(
        "reminders",
        {
            "select": COLUMNS_WITH_NONCE,
            "status": "eq.active",
            "next_send_date": f"lte.{day.isoformat()}",
            "order": "next_send_date.asc",
            "limit": str(s.reminder_daily_cap + 1),
        },
    )
    stats = {"due": len(rows), "sent": 0, "paused": 0, "finished": 0, "skipped": 0, "failed": 0}
    stats["capped"] = max(0, len(rows) - s.reminder_daily_cap)
    for row in rows[: s.reminder_daily_cap]:
        if time.monotonic() > deadline:
            stats["capped"] += 1
            continue
        stats[await send_day(db, provider, row, day, s)] += 1
    return stats
