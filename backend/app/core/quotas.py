"""Per-session caps on expensive actions (SPEC 9: "cap total LLM calls per session").

Every LLM-consuming endpoint calls `consume_quota(db, session_id, action)` BEFORE doing the
work. The counter lives in Postgres (`session_usage`, migration 20261106000004_security.sql) and
is incremented atomically by the `consume_quota` SQL function, so it holds across serverless
instances and concurrent requests. When the budget is used up we return 429.

This is a per-session cap, not a per-IP rate limit: an attacker can still create new sessions.
That part is handled by `app.core.rate_limit` (Upstash) + Turnstile once enabled.
"""

from typing import Final
from uuid import UUID

from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.client import SupabaseRest

log = get_logger(__name__)

# Generous for honest use (a user may fix a typo in their CV and re-run), tight enough that one
# guest token can't burn the free-tier LLM quota. Interview actions are used by the Phase 3 router.
SESSION_QUOTAS: Final[dict[str, int]] = {
    "upload": 5,  # CV + JD uploads (each replaces the old analysis)
    "analysis": 3,  # fresh gap analyses (cached results are free)
    "interview_start": 3,  # interview plans
    "interview_answer": 40,  # answers incl. follow-ups (~6 questions x 2 per interview x 3)
    "report": 3,  # report generations
    "email": 3,  # report emails
}


class QuotaExceededError(AppError):
    def __init__(self, action: str) -> None:
        super().__init__(
            "quota_exceeded",
            f"You've reached the limit for this action ({action}) in this session. "
            "Start a new session to continue.",
            status_code=429,
        )


async def consume_quota(db: SupabaseRest, session_id: UUID, action: str) -> None:
    """Take one unit of `action` budget for this session, or raise QuotaExceededError (429)."""
    limit = SESSION_QUOTAS[action]  # KeyError on typos is intentional (fails in tests)
    allowed = await db.rpc(
        "consume_quota", {"p_session_id": str(session_id), "p_action": action, "p_limit": limit}
    )
    if allowed is not True:
        log.warning(
            "quota_exceeded",
            extra={"extra_fields": {"session_id": str(session_id), "action": action}},
        )
        raise QuotaExceededError(action)
