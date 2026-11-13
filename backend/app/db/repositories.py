"""Data access for sessions and documents. All queries are scoped by session id."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.errors import session_not_found
from app.core.security import token_matches
from app.db.client import SupabaseRest

SESSION_COLUMNS = (
    "id,guest_token_hash,status,role_title,mode,difficulty,interview_type,"
    "email_opt_in,is_demo,created_at,expires_at"
)


async def get_owned_session(
    db: SupabaseRest, session_id: UUID, token: str | None
) -> dict[str, Any]:
    rows = await db.select(
        "sessions", {"select": SESSION_COLUMNS, "id": f"eq.{session_id}", "limit": "1"}
    )
    if not rows:
        raise session_not_found()
    row = rows[0]
    if not token_matches(token, row["guest_token_hash"]):
        raise session_not_found()
    expires = datetime.fromisoformat(row["expires_at"])
    if expires < datetime.now(UTC):
        raise session_not_found()
    return row


async def get_documents(db: SupabaseRest, session_id: UUID) -> dict[str, dict[str, Any]]:
    rows = await db.select(
        "documents",
        {"select": "id,kind,raw_text,structured,content_hash", "session_id": f"eq.{session_id}"},
    )
    return {r["kind"]: r for r in rows}


async def cached_jd_structure(db: SupabaseRest, content_hash: str) -> dict[str, Any] | None:
    """Reuse a previous extraction of the exact same JD text (saves an LLM call)."""
    rows = await db.select(
        "documents",
        {
            "select": "structured",
            "kind": "eq.jd",
            "content_hash": f"eq.{content_hash}",
            "structured": "not.is.null",
            "limit": "1",
        },
    )
    return rows[0]["structured"] if rows else None


async def save_document(
    db: SupabaseRest,
    session_id: UUID,
    kind: str,
    raw_text: str,
    content_hash: str,
    structured: dict[str, Any] | None = None,
) -> None:
    """Replace this session's CV or JD. Cascades remove old chunks and the old analysis.

    `structured` starts as `{"ats_file": FileSignals}` for an uploaded CV (layout facts only the
    file can tell); the analysis later adds the extracted profile next to it."""
    await db.delete("documents", {"session_id": f"eq.{session_id}", "kind": f"eq.{kind}"})
    await db.delete("gap_analyses", {"session_id": f"eq.{session_id}"})
    await db.insert(
        "documents",
        [
            {
                "session_id": str(session_id),
                "kind": kind,
                "raw_text": raw_text,
                "content_hash": content_hash,
                "structured": structured,
            }
        ],
    )
