"""Transactional email behind a tiny interface, so the provider can be swapped (SPEC 6.6).

- `EmailProvider`: `send(to, subject, html, text, idempotency_key)`.
- `ResendProvider`: Resend's HTTP API via the shared httpx client (no SDK):
  `POST https://api.resend.com/emails`, `Authorization: Bearer <key>`, JSON
  `{from, to: [..], subject, html, text}`; success returns `{"id": ...}`. The optional
  `Idempotency-Key` header (max 256 chars, kept 24 h) makes a double click send one email.
  Docs checked 2026-11-12.
- `get_email_provider()` returns None until RESEND_API_KEY and EMAIL_FROM are both set; the router
  then answers 503 `email_not_configured` and the UI disables the button. Tests never send.

Privacy: the recipient address and the report content are never logged, only the HTTP status.
All user-controlled text placed in the email HTML is escaped (`html.escape`).

Swapping providers (e.g. Brevo): add a class with the same `send` signature and return it from
`get_email_provider()`. Phase 7 reminder emails reuse the same interface.
"""

from html import escape
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.http import get_http_client
from app.core.logging import get_logger
from app.schemas.report import Report

log = get_logger(__name__)

RESEND_URL = "https://api.resend.com/emails"
SENDER_NAME = "HireReady AI"
SEND_TIMEOUT_S = 15.0


class EmailError(Exception):
    pass


class EmailProvider(Protocol):
    async def send(
        self, *, to: str, subject: str, html: str, text: str, idempotency_key: str | None = None
    ) -> None: ...


def _sender(email_from: str) -> str:
    """EMAIL_FROM may be a bare address or already "Name <address>"."""
    return email_from if "<" in email_from else f"{SENDER_NAME} <{email_from}>"


class ResendProvider:
    def __init__(self, api_key: str, sender: str, client: httpx.AsyncClient) -> None:
        self._key = api_key
        self._sender = _sender(sender)
        self._client = client

    async def send(
        self, *, to: str, subject: str, html: str, text: str, idempotency_key: str | None = None
    ) -> None:
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:256]
        try:
            resp = await self._client.post(
                RESEND_URL,
                headers=headers,
                json={
                    "from": self._sender,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                    "text": text,
                    "tags": [{"name": "kind", "value": "report"}],
                },
                timeout=SEND_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            raise EmailError(type(exc).__name__) from exc
        if resp.status_code not in (200, 201, 202):
            # Never log the address or the body; the status is enough to debug.
            log.warning("email_failed", extra={"extra_fields": {"status": resp.status_code}})
            raise EmailError(f"Resend status {resp.status_code}")


def email_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(s.resend_api_key and s.email_from)


def get_email_provider(settings: Settings | None = None) -> EmailProvider | None:
    s = settings or get_settings()
    if not s.resend_api_key or not s.email_from:
        return None
    return ResendProvider(s.resend_api_key.get_secret_value(), s.email_from, get_http_client())


# ------------------------------------------------------------------ rendering

_MUTED = "color:#555;font-size:13px"


def _button(href: str, label: str) -> str:
    return (
        f'<p><a href="{escape(href, quote=True)}" style="display:inline-block;padding:10px 16px;'
        'background:#4f46e5;color:#fff;border-radius:8px;text-decoration:none">'
        f"{escape(label)}</a></p>"
    )


def render_report_email(
    report: Report, report_link: str, share_link: str | None = None
) -> tuple[str, str, str]:
    """(subject, html, text): a short summary + link, never the transcripts (they are sensitive
    and emails get forwarded) and well under Gmail's ~102 KB clipping limit.

    Contents: band + score, the hiring signal, the top 3 fixes, per-question scores, Day 1 of the
    plan in full and the other days' focus. The session link only works in the browser that holds
    the guest token, so an active share link (if the user created one) is offered too."""
    r, e = report.readiness, report.employer
    role = report.role_title or "your target role"
    subject = f"Your HireReady interview report: {r.band_label}, {r.score}/100"
    fixes = report.improvements[:3]
    day1, later = (report.prep_plan[0], report.prep_plan[1:]) if report.prep_plan else (None, [])
    next_line = (
        f"{r.points_to_next_band} points to {r.next_band_label}."
        if r.next_band_label and r.points_to_next_band is not None
        else ""
    )

    html = (
        "<div style='font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:600px;"
        "line-height:1.5;color:#111'>"
        f"<h2 style='margin-bottom:4px'>Your practice interview report: {escape(role)}</h2>"
        f"<p style='font-size:20px;margin:8px 0'><strong>{escape(r.band_label)}</strong> "
        f"&middot; {r.score}/100</p>"
        f"<p style='{_MUTED}'>Interview {r.interview_score}"
        + (f" &middot; CV match {r.match_score}" if r.match_score is not None else "")
        + f". {escape(next_line)} Simulated hiring-manager signal: "
        f"{escape(e.verdict_label)}.</p>"
        + (
            "<h3>Top things to fix</h3><ol>"
            + "".join(
                f"<li><strong>{escape(t.title)}</strong>: {escape(t.detail)}</li>" for t in fixes
            )
            + "</ol>"
            if fixes
            else ""
        )
        + "<h3>Per question</h3><ul>"
        + "".join(
            f"<li>{escape(q.label)}: {escape(q.level_label)}, {q.score}/100</li>"
            for q in report.questions
        )
        + "</ul>"
        + (
            f"<h3>Day 1: {escape(day1.focus)}</h3><ul>"
            + "".join(f"<li>{escape(t)}</li>" for t in day1.tasks)
            + "</ul>"
            if day1
            else ""
        )
        + (
            "<p style='color:#555'>Next: "
            + escape(" · ".join(f"Day {d.day} {d.focus}" for d in later))
            + "</p>"
            if later
            else ""
        )
        + (_button(share_link, "View the full report") if share_link else "")
        + (
            f'<p><a href="{escape(report_link, quote=True)}">Open your report</a> '
            "(works in the browser you took the interview in).</p>"
        )
        + f"<p style='{_MUTED}'>You asked HireReady AI to send this email; we don't add you to "
        "any list. AI-generated practice feedback, not a hiring decision. Guest data is "
        "deleted automatically after 7 days.</p></div>"
    )
    lines = [
        f"Your practice interview report: {role}",
        "",
        f"{r.band_label} - {r.score}/100",
        f"Interview {r.interview_score}"
        + (f", CV match {r.match_score}" if r.match_score is not None else "")
        + f". {next_line} Simulated hiring-manager signal: {e.verdict_label}.",
    ]
    if fixes:
        lines += ["", "Top things to fix:"]
        lines += [f"{i}. {t.title}: {t.detail}" for i, t in enumerate(fixes, 1)]
    lines += ["", "Per question:"]
    lines += [f"- {q.label}: {q.level_label}, {q.score}/100" for q in report.questions]
    if day1:
        lines += ["", f"Day 1: {day1.focus}"] + [f"- {t}" for t in day1.tasks]
    if later:
        lines.append("Next: " + " | ".join(f"Day {d.day} {d.focus}" for d in later))
    if share_link:
        lines += ["", f"Full report (read-only link): {share_link}"]
    lines += [
        "",
        f"Your report (in the browser you used): {report_link}",
        "",
        "AI-generated practice feedback, not a hiring decision.",
    ]
    text = "\n".join(lines) + "\n"
    return subject, html, text
