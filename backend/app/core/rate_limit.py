"""Per-IP / per-key rate limiting (SPEC 9).

Two backends, picked from the environment:
- `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN` set: `UpstashRateLimiter`, a fixed-window
  counter over Upstash's REST API (`INCR` + `EXPIRE ... NX` in one pipeline call). Shared by every
  serverless instance, so it is the real limit in production.
- Unset (local dev, tests, or before the Upstash account exists): `InMemoryRateLimiter`, the same
  fixed window in this process's memory. On Vercel each warm instance has its own counters, so it
  is weaker, but much better than nothing.

What happens when Upstash is configured but unreachable is decided PER POLICY (`on_outage`):
- "local": fall back to the in-process counter (LLM-spending endpoints: availability matters, and
  the per-session DB quotas plus the global daily LLM budget still cap the spend).
- "closed": refuse with 429 (email sending: a free form that emails any address is a spam relay,
  and email is never essential to the core flow, so we'd rather not send).
- "open": allow (cheap, read-only endpoints).
The table is in docs/SECURITY.md ("Rate limits: fail-open or fail-closed").

Usage in a router:
    await enforce_rate_limit(request, "session_create")
Without a request (e.g. per-recipient email limits inside a background task):
    if not await allow("email_recipient", subject=email_hash): ...
"""

import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal, Protocol

import httpx
from fastapi import Request
from starlette.exceptions import HTTPException

from app.core.config import Settings, get_settings
from app.core.http import get_http_client
from app.core.logging import get_logger
from app.core.redis import RedisUnavailableError, UpstashRedis
from app.core.security import hash_token

log = get_logger(__name__)

Outage = Literal["local", "closed", "open"]


@dataclass(frozen=True)
class Policy:
    limit: int
    window_s: int
    on_outage: Outage = "local"


# SPEC 9 targets. Keys are per client IP unless a caller passes its own subject.
POLICIES: Final[dict[str, Policy]] = {
    "session_create": Policy(limit=10, window_s=3600),
    "upload": Policy(limit=10, window_s=3600),
    "analyze": Policy(limit=10, window_s=3600),
    "interview_start": Policy(limit=3, window_s=86400),  # "3 full interviews/day per guest IP"
    "interview_answer": Policy(limit=30, window_s=3600),  # "30 answer submissions/hour"
    "report": Policy(limit=10, window_s=3600),  # fresh report builds (cached reads are free)
    "email": Policy(limit=5, window_s=3600, on_outage="closed"),
    # Per RECIPIENT (subject = hash of the address), across all sessions: stops HireReady being
    # used to flood one inbox. Report emails + reminder confirmations count; daily reminders don't.
    "email_recipient": Policy(limit=3, window_s=86400, on_outage="closed"),
    "reminder_subscribe": Policy(limit=5, window_s=3600, on_outage="closed"),
    # Public token links in reminder emails (confirm / done / resume / unsubscribe / status).
    "reminder_link": Policy(limit=60, window_s=3600, on_outage="open"),
    "public_status": Policy(limit=60, window_s=3600, on_outage="open"),
}


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after_s: int = 0


class RateLimiter(Protocol):
    async def hit(self, key: str, policy: Policy) -> RateLimitResult: ...


def _window(now: float, policy: Policy) -> tuple[int, int]:
    """(window number, seconds until it ends)."""
    window = int(now // policy.window_s)
    return window, max(1, int((window + 1) * policy.window_s - now))


class NoopRateLimiter:
    async def hit(self, key: str, policy: Policy) -> RateLimitResult:
        return RateLimitResult(allowed=True)


class InMemoryRateLimiter:
    """Fixed window in this process. Old windows are pruned so memory stays bounded."""

    MAX_KEYS = 50_000

    def __init__(self, now: Callable[[], float] | None = None) -> None:
        self._now = now or time.time
        self._counts: dict[str, int] = {}

    async def hit(self, key: str, policy: Policy) -> RateLimitResult:
        window, retry_after = _window(self._now(), policy)
        k = f"{key}:{policy.window_s}:{window}"
        if k not in self._counts and len(self._counts) >= self.MAX_KEYS:
            self._prune()
        self._counts[k] = self._counts.get(k, 0) + 1
        if self._counts[k] <= policy.limit:
            return RateLimitResult(allowed=True)
        return RateLimitResult(allowed=False, retry_after_s=retry_after)

    def _prune(self) -> None:
        now = self._now()
        keep: dict[str, int] = {}
        for k, v in self._counts.items():
            _, size, window = k.rsplit(":", 2)
            if int(window) == int(now // int(size)):
                keep[k] = v
        self._counts = keep if len(keep) < self.MAX_KEYS else {}


class UpstashRateLimiter:
    def __init__(
        self,
        url: str,
        token: str,
        client: httpx.AsyncClient,
        now: Callable[[], float] | None = None,
        fallback: RateLimiter | None = None,
    ) -> None:
        self._redis = UpstashRedis(url, token, client)
        self._now = now or time.time
        self._fallback = fallback or InMemoryRateLimiter(self._now)

    async def hit(self, key: str, policy: Policy) -> RateLimitResult:
        now = self._now()
        window, retry_after = _window(now, policy)
        redis_key = f"rl:{key}:{window}"
        try:
            result = await self._redis.pipeline(
                [["INCR", redis_key], ["EXPIRE", redis_key, str(policy.window_s), "NX"]]
            )
            count = int(result[0])
        except (RedisUnavailableError, TypeError, ValueError) as exc:
            log.warning(
                "rate_limit_unavailable",
                extra={"extra_fields": {"error": type(exc).__name__, "mode": policy.on_outage}},
            )
            if policy.on_outage == "closed":
                return RateLimitResult(allowed=False, retry_after_s=60)
            if policy.on_outage == "open":
                return RateLimitResult(allowed=True)
            return await self._fallback.hit(key, policy)
        if count <= policy.limit:
            return RateLimitResult(allowed=True)
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
            _limiter = InMemoryRateLimiter()
    return _limiter


# The Next.js proxy (frontend/proxy.ts) sets these on every /api/* request it forwards.
PROXY_IP_HEADER = "x-hireready-client-ip"
PROXY_SECRET_HEADER = "x-hireready-proxy-secret"  # noqa: S105 (a header name, not a secret)


def client_ip_with_source(request: Request, settings: Settings | None = None) -> tuple[str, str]:
    """(client IP, which header it came from).

    Why the proxy header: the browser calls the frontend, and the Next.js rewrite then calls the
    backend's own Vercel deployment from Vercel's network. The backend's platform headers
    (`x-vercel-forwarded-for`, `x-forwarded-for`) then describe THAT hop, so every user could
    share one bucket. `frontend/proxy.ts` copies the browser's IP (which Vercel sets on the
    frontend request) into `X-HireReady-Client-IP`, with a shared secret so nobody calling the
    backend URL directly can pick their own IP. Check what the deployed app sees with
    `GET /api/v1/health/client-ip` (docs/SECURITY.md).

    On Vercel the platform overwrites client-supplied `x-forwarded-for`, so those are trusted
    next; locally we fall back to the socket peer.
    """
    s = settings or get_settings()
    if s.client_ip_header_secret:
        sent = request.headers.get(PROXY_SECRET_HEADER, "")
        ip = request.headers.get(PROXY_IP_HEADER, "").strip()
        expected = s.client_ip_header_secret.get_secret_value()
        if ip and hmac.compare_digest(sent.encode(), expected.encode()):
            return ip.split(",")[0].strip()[:64], "proxy"
    for header in ("x-vercel-forwarded-for", "x-forwarded-for", "x-real-ip"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()[:64], header
    return (request.client.host if request.client else "unknown"), "socket"


def client_ip(request: Request) -> str:
    return client_ip_with_source(request)[0]


def _too_many(retry_after_s: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail="Too many requests. Please wait a little and try again.",
        headers={"Retry-After": str(retry_after_s)},
    )


async def check(name: str, subject: str, limiter: RateLimiter | None = None) -> RateLimitResult:
    """Count one hit of policy `name` for `subject` (already hashed / non-personal)."""
    return await (limiter or get_rate_limiter()).hit(f"{name}:{subject}", POLICIES[name])


async def allow(name: str, *, subject: str, limiter: RateLimiter | None = None) -> bool:
    result = await check(name, subject, limiter)
    if not result.allowed:
        log.warning("rate_limited", extra={"extra_fields": {"policy": name}})
    return result.allowed


async def enforce_rate_limit(
    request: Request,
    name: str,
    *,
    subject: str | None = None,
    limiter: RateLimiter | None = None,
) -> None:
    """Raise 429 (with Retry-After) when `name`'s policy is exceeded for this IP / subject."""
    # Hash the IP so raw IPs never land in Redis keys (they're personal data under GDPR).
    who = subject or f"ip:{hash_token(client_ip(request))[:32]}"
    result = await check(name, who, limiter)
    if not result.allowed:
        log.warning("rate_limited", extra={"extra_fields": {"policy": name}})
        raise _too_many(result.retry_after_s)


async def enforce_subject_limit(
    name: str, subject: str, *, limiter: RateLimiter | None = None
) -> None:
    """Like enforce_rate_limit, keyed only by `subject` (e.g. a hashed email address)."""
    result = await check(name, subject, limiter)
    if not result.allowed:
        log.warning("rate_limited", extra={"extra_fields": {"policy": name}})
        raise _too_many(result.retry_after_s)
