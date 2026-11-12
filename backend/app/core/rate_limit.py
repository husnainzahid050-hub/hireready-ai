"""Per-IP / per-key rate limiting (SPEC 9), switched on by env vars.

- No `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN`: `NoopRateLimiter` (always allows).
  Local dev and tests need no account.
- Both set: `UpstashRateLimiter`, a fixed-window counter over Upstash's REST API
  (`INCR` + `EXPIRE ... NX` in one pipeline call). Works across serverless instances.

If Upstash is down we FAIL OPEN (allow + log a warning): availability of the app matters more
than a perfect limit, and the per-session DB quotas (`app.core.quotas`) still cap LLM spend.

Usage in a router:
    await enforce_rate_limit(request, "session_create")
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol

import httpx
from fastapi import Request
from starlette.exceptions import HTTPException

from app.core.config import Settings, get_settings
from app.core.http import get_http_client
from app.core.logging import get_logger
from app.core.security import hash_token

log = get_logger(__name__)


@dataclass(frozen=True)
class Policy:
    limit: int
    window_s: int


# SPEC 9 targets. Keys are per client IP unless a caller passes its own subject.
POLICIES: Final[dict[str, Policy]] = {
    "session_create": Policy(limit=10, window_s=3600),
    "upload": Policy(limit=10, window_s=3600),
    "analyze": Policy(limit=10, window_s=3600),
    "interview_start": Policy(limit=3, window_s=86400),  # "3 full interviews/day per guest IP"
    "interview_answer": Policy(limit=30, window_s=3600),  # "30 answer submissions/hour"
    "report": Policy(limit=10, window_s=3600),  # fresh report builds (cached reads are free)
    "email": Policy(limit=5, window_s=3600),
}


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_s: int = 0


class RateLimiter(Protocol):
    async def hit(self, key: str, policy: Policy) -> RateLimitResult: ...


class NoopRateLimiter:
    async def hit(self, key: str, policy: Policy) -> RateLimitResult:
        return RateLimitResult(allowed=True)


class UpstashRateLimiter:
    def __init__(
        self,
        url: str,
        token: str,
        client: httpx.AsyncClient,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._url = url.rstrip("/") + "/pipeline"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = client
        self._now = now or time.time

    async def hit(self, key: str, policy: Policy) -> RateLimitResult:
        now = self._now()
        window = int(now // policy.window_s)
        redis_key = f"rl:{key}:{window}"
        try:
            resp = await self._client.post(
                self._url,
                headers=self._headers,
                json=[["INCR", redis_key], ["EXPIRE", redis_key, str(policy.window_s), "NX"]],
                timeout=2.0,
            )
            resp.raise_for_status()
            count = int(resp.json()[0]["result"])
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            log.warning(
                "rate_limit_unavailable", extra={"extra_fields": {"error": type(exc).__name__}}
            )
            return RateLimitResult(allowed=True)
        if count <= policy.limit:
            return RateLimitResult(allowed=True)
        retry_after = max(1, int((window + 1) * policy.window_s - now))
        return RateLimitResult(allowed=False, retry_after_s=retry_after)


_limiter: RateLimiter | None = None


def get_rate_limiter(settings: Settings | None = None) -> RateLimiter:
    global _limiter
    if _limiter is None:
        s = settings or get_settings()
        if s.upstash_redis_rest_url and s.upstash_redis_rest_token:
            _limiter = UpstashRateLimiter(
                s.upstash_redis_rest_url,
                s.upstash_redis_rest_token.get_secret_value(),
                get_http_client(),
            )
        else:
            _limiter = NoopRateLimiter()
    return _limiter


def client_ip(request: Request) -> str:
    """Best-effort client IP.

    On Vercel the platform sets `x-vercel-forwarded-for` / `x-forwarded-for` itself and overwrites
    client-supplied values, so the first entry is trustworthy there. Elsewhere (local dev) we fall
    back to the socket peer. Verify on the deployed app that requests proxied through the Next.js
    rewrite carry the *browser's* IP (see docs/SECURITY.md, "Pending").
    """
    for header in ("x-vercel-forwarded-for", "x-forwarded-for", "x-real-ip"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(
    request: Request,
    name: str,
    *,
    subject: str | None = None,
    limiter: RateLimiter | None = None,
) -> None:
    """Raise 429 (with Retry-After) when `name`'s policy is exceeded for this IP / subject."""
    policy = POLICIES[name]
    # Hash the IP so raw IPs never land in Redis keys (they're personal data under GDPR).
    who = subject or f"ip:{hash_token(client_ip(request))[:32]}"
    result = await (limiter or get_rate_limiter()).hit(f"{name}:{who}", policy)
    if not result.allowed:
        log.warning("rate_limited", extra={"extra_fields": {"policy": name}})
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a little and try again.",
            headers={"Retry-After": str(result.retry_after_s)},
        )
