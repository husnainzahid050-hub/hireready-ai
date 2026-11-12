"""Global daily LLM-call budget: a circuit breaker against "denial of wallet" (OWASP LLM10).

Per-IP limits are beaten by proxy pools and per-session quotas by new sessions, so the last layer
is a single counter for the whole app: `llm_budget:{YYYY-MM-DD}` (UTC) in Upstash Redis,
incremented by the estimated number of LLM calls of each fresh, LLM-spending action.

- Above `LLM_DAILY_SOFT_RATIO` x `LLM_DAILY_BUDGET` (default 80%): demo sessions may only be served
  from the demo cache (`copy_demo_analysis`); a fresh demo LLM action gets 503. Real users keep
  going, since the demo is the cheapest thing to give up.
- Above the budget: every fresh LLM action gets 503 `daily_budget_exhausted` with Retry-After
  set to the seconds until 00:00 UTC. Cached results (saved analysis, saved report) stay free.

Redis unset or unreachable: an in-process counter is used instead (weaker on serverless, where
each instance counts separately, but it never blocks the app because Redis is down).

The weights are estimates of how many provider calls each action makes (see LLM_COST); they
are deliberately counted per ACTION at the router, not inside the LLM client, so the budget is
checked before any work starts and a refused request costs nothing.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.redis import RedisUnavailableError, get_redis

log = get_logger(__name__)

# Provider calls per fresh action (analysis: CV + JD extraction, evidence judging, insights).
LLM_COST: Final[dict[str, int]] = {
    "analysis": 4,
    "interview_start": 1,
    "interview_answer": 2,  # scoring (+ Whisper for a voice answer)
    "report": 1,
}

EXHAUSTED_MESSAGE = (
    "HireReady hit today's free-tier AI limit. Please try again after 00:00 UTC "
    "(HireReady runs on free tiers)."
)
DEMO_PAUSED_MESSAGE = (
    "The live demo is resting for today to save free-tier AI quota. Upload your own CV to "
    "continue, or try the demo again after 00:00 UTC."
)


class BudgetExhaustedError(AppError):
    def __init__(self, message: str, retry_after_s: int) -> None:
        super().__init__(
            "daily_budget_exhausted",
            message,
            status_code=503,
            headers={"Retry-After": str(retry_after_s)},
        )


def seconds_until_utc_midnight(now: float) -> int:
    return max(1, 86400 - int(now) % 86400)


class _LocalCounter:
    def __init__(self) -> None:
        self.day = ""
        self.count = 0

    def add(self, day: str, n: int) -> int:
        if day != self.day:
            self.day, self.count = day, 0
        self.count += n
        return self.count


_local = _LocalCounter()


def reset_local_budget() -> None:
    """Tests: start each test with an empty in-process counter."""
    global _local
    _local = _LocalCounter()


async def _increment(day: str, n: int) -> int:
    redis = get_redis()
    if redis is not None:
        key = f"llm_budget:{day}"
        try:
            result = await redis.pipeline(
                [["INCRBY", key, str(n)], ["EXPIRE", key, str(2 * 86400), "NX"]]
            )
            return int(result[0])
        except (RedisUnavailableError, TypeError, ValueError) as exc:
            log.warning(
                "llm_budget_redis_unavailable",
                extra={"extra_fields": {"error": type(exc).__name__}},
            )
    return _local.add(day, n)


async def reserve_llm_calls(
    action: str,
    *,
    demo: bool = False,
    settings: Settings | None = None,
    now: Callable[[], float] = time.time,
) -> None:
    """Charge `action`'s estimated LLM calls to today's global budget, or raise 503."""
    s = settings or get_settings()
    t = now()
    day = datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d")
    used = await _increment(day, LLM_COST[action])
    retry = seconds_until_utc_midnight(t)
    if used > s.llm_daily_budget:
        log.warning("llm_budget_exhausted", extra={"extra_fields": {"action": action}})
        raise BudgetExhaustedError(EXHAUSTED_MESSAGE, retry)
    if demo and used > s.llm_daily_budget * s.llm_daily_soft_ratio:
        log.warning("llm_budget_soft_limit_demo", extra={"extra_fields": {"action": action}})
        raise BudgetExhaustedError(DEMO_PAUSED_MESSAGE, retry)
