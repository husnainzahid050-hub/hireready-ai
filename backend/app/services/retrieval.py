"""Hybrid retrieval (vector + full-text, fused with RRF in Postgres).

The heavy lifting is in the `hybrid_search` SQL function
(supabase/migrations/20261106000002_hybrid_search.sql). This service just embeds
the query and calls it with the right filter.
"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.db.client import SupabaseRest
from app.services.embeddings import Embedder, to_pgvector

Level = Literal["junior", "mid"]
MAX_QUERY_CHARS = 1000


class RetrievedChunk(BaseModel):
    id: UUID
    content: str
    score: float
    metadata: dict[str, Any] = {}
    competency: str | None = None
    level: str | None = None
    source_file: str | None = None
    document_id: UUID | None = None


class Retriever:
    def __init__(self, db: SupabaseRest, embedder: Embedder) -> None:
        self._db = db
        self._embedder = embedder

    async def _search(self, query: str, k: int, filter_: dict[str, str]) -> list[RetrievedChunk]:
        query = query.strip()[:MAX_QUERY_CHARS]
        if not query:
            return []
        [vector] = await self._embedder.embed([query], "RETRIEVAL_QUERY")
        rows = await self._db.rpc(
            "hybrid_search",
            {
                "query_embedding": to_pgvector(vector),
                "query_text": query,
                "match_count": max(1, min(k, 50)),
                "filter": filter_,
            },
        )
        return [RetrievedChunk.model_validate(r) for r in rows or []]

    async def search_rubric(
        self,
        query: str,
        *,
        competency: str | None = None,
        level: Level | None = None,
        k: int = 5,
    ) -> list[RetrievedChunk]:
        f: dict[str, str] = {"source": "knowledge"}
        if competency:
            f["competency"] = competency
        if level:
            f["level"] = level
        return await self._search(query, k, f)

    async def search_cv(self, session_id: UUID, query: str, *, k: int = 5) -> list[RetrievedChunk]:
        return await self._search(query, k, {"source": "cv", "session_id": str(session_id)})
