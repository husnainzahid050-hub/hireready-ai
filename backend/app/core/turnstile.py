"""Cloudflare Turnstile bot check on session creation (SPEC 9), switched on by env var.

- `TURNSTILE_SECRET_KEY` unset: `NoopTurnstile` (always passes) for local dev and tests.
- Set: `CloudflareTurnstile` verifies the token from the `X-Turnstile-Token` request header
  with Cloudflare's siteverify API. This FAILS CLOSED: a missing/invalid token, or Cloudflare
  being unreachable, rejects the request (a bot check that can be skipped is no check).

The frontend renders the widget with `NEXT_PUBLIC_TURNSTILE_SITE_KEY` (the only public key) and
sends the token it receives as the `X-Turnstile-Token` header on `POST /sessions`.
"""

from typing import Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.http import get_http_client
from app.core.logging import get_logger

log = get_logger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
MAX_TOKEN_CHARS = 2048  # Cloudflare documents a max token length of 2048 characters


class TurnstileVerifier(Protocol):
    async def verify(self, token: str | None, remote_ip: str | None) -> bool: ...


class NoopTurnstile:
    async def verify(self, token: str | None, remote_ip: str | None) -> bool:
        return True


class CloudflareTurnstile:
    def __init__(self, secret: str, client: httpx.AsyncClient) -> None:
        self._secret = secret
        self._client = client

    async def verify(self, token: str | None, remote_ip: str | None) -> bool:
        if not token or len(token) > MAX_TOKEN_CHARS:
            return False
        data = {"secret": self._secret, "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip
        try:
            resp = await self._client.post(SITEVERIFY_URL, data=data, timeout=5.0)
            ok = resp.status_code == 200 and resp.json().get("success") is True
        except (httpx.HTTPError, ValueError) as exc:
            log.warning(
                "turnstile_unavailable", extra={"extra_fields": {"error": type(exc).__name__}}
            )
            return False
        if not ok:
            log.info("turnstile_failed")
        return ok


def get_turnstile(settings: Settings | None = None) -> TurnstileVerifier:
    s = settings or get_settings()
    if s.turnstile_secret_key:
        return CloudflareTurnstile(s.turnstile_secret_key.get_secret_value(), get_http_client())
    return NoopTurnstile()


async def require_human(
    token: str | None, remote_ip: str | None, verifier: TurnstileVerifier | None = None
) -> None:
    if not await (verifier or get_turnstile()).verify(token, remote_ip):
        raise AppError(
            "bot_check_failed",
            "We couldn't verify you're human. Please refresh the page and try again.",
            status_code=403,
        )
