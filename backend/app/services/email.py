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
from app.schemas.report import Flag, Report

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


def _flag_items(flags: list[Flag]) -> str:
    return "".join(
        f"<li><strong>{escape(f.title)}</strong> ({escape(f.answer_ref)}): {escape(f.detail)}</li>"
        for f in flags
    )


def render_report_email(
    report: Report, report_link: str, share_link: str | None = None
) -> tuple[str, str, str]:
    """(subject, html, text). Self-contained: the report page needs the guest token that lives
    in the browser the interview was taken in, so the email carries the essentials itself."""
    r, e = report.readiness, report.employer
    role = report.role_title or "your target role"
    subject = f"Your HireReady interview report: {r.score}/100 ({r.band_label})"

    q_rows = "".join(
        f"<tr><td style='padding:4px 8px'>{escape(q.label)}</td>"
        f"<td style='padding:4px 8px'>{q.score}/100</td>"
        f"<td style='padding:4px 8px'>{escape(q.tip)}</td></tr>"
        for q in report.questions
    )
    plan_items = "".join(
        f"<li><strong>Day {d.day}: {escape(d.focus)}</strong><br>{escape('; '.join(d.tasks))}</li>"
        for d in report.prep_plan
    )
    speech_html = (
        f"<h3>Speaking</h3><p>{escape(report.speech.guidance)} Filler words: "
        f"{report.speech.filler_total}. Long pauses: {report.speech.long_pauses_total}.</p>"
        if report.speech
        else ""
    )
    share_html = (
        f'<p>Share link (read-only): <a href="{escape(share_link, quote=True)}">'
        f"{escape(share_link)}</a></p>"
        if share_link
        else ""
    )
    html = (
        "<div style='font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:640px;"
        "line-height:1.5;color:#111'>"
        f"<h2>Your mock interview report for {escape(role)}</h2>"
        f"<p style='font-size:18px'><strong>Readiness: {r.score}/100</strong> "
        f"({escape(r.band_label)}). Hiring signal: <strong>{escape(e.verdict_label)}</strong>.</p>"
        f"<p style='{_MUTED}'>{escape(r.formula)}</p>"
        f"<h3>The hiring manager's take</h3><p>{escape(e.reaction)}</p>"
        f"<h3>Green flags</h3><ul>{_flag_items(e.green_flags)}</ul>"
        f"<h3>Red flags</h3><ul>{_flag_items(e.red_flags)}</ul>"
        "<h3>Per question</h3><table style='border-collapse:collapse;font-size:14px'>"
        "<tr><th align='left' style='padding:4px 8px'>Q</th>"
        "<th align='left' style='padding:4px 8px'>Score</th>"
        f"<th align='left' style='padding:4px 8px'>One tip</th></tr>{q_rows}</table>"
        f"{speech_html}"
        f"<h3>Your 7-day plan</h3><ol style='padding-left:0;list-style:none'>{plan_items}</ol>"
        f"{share_html}"
        f'<p><a href="{escape(report_link, quote=True)}">Open the full report</a> '
        "(works in the browser you took the interview in).</p>"
        f"<p style='{_MUTED}'>You asked HireReady AI to send this email; we don't add you to "
        "any list. Guest data is deleted automatically after 7 days.</p></div>"
    )
    text = (
        f"Your mock interview report for {role}\n\n"
        f"Readiness: {r.score}/100 ({r.band_label}). Hiring signal: {e.verdict_label}.\n"
        f"{r.formula}\n\n"
        f"The hiring manager's take:\n{e.reaction}\n\n"
        "Green flags:\n"
        + "".join(f"- {f.title} ({f.answer_ref}): {f.detail}\n" for f in e.green_flags)
        + "\nRed flags:\n"
        + "".join(f"- {f.title} ({f.answer_ref}): {f.detail}\n" for f in e.red_flags)
        + "\nPer question:\n"
        + "".join(f"- {q.label}: {q.score}/100. Tip: {q.tip}\n" for q in report.questions)
        + (f"\nSpeaking: {report.speech.guidance}\n" if report.speech else "")
        + "\nYour 7-day plan:\n"
        + "".join(f"Day {d.day}: {d.focus}. {'; '.join(d.tasks)}\n" for d in report.prep_plan)
        + (f"\nShare link (read-only): {share_link}\n" if share_link else "")
        + f"\nFull report (in the browser you used): {report_link}\n"
    )
    return subject, html, text
