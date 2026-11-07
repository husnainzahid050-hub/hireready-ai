"""Hybrid retrieval (vector + full-text, fused with RRF in Postgres).

The heavy lifting is in the `hybrid_search` SQL function
(supabase/migrations/20261106000002_hybrid_search.sql). This service just embeds
the query and calls it with the right filter.
"""

import asyncio
from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.db.client import SupabaseRest
from app.services.embeddings import Embedder, to_pgvector

Level = Literal["junior", "mid"]


def rubric_level(difficulty: str | None) -> Level:
    """The knowledge base has junior and mid content; anything else maps to junior."""
    return "mid" if difficulty == "mid" else "junior"


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

    async def _rpc(
        self, query: str, vector: list[float], k: int, filter_: dict[str, str]
    ) -> list[RetrievedChunk]:
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

    async def _search(self, query: str, k: int, filter_: dict[str, str]) -> list[RetrievedChunk]:
        query = query.strip()[:MAX_QUERY_CHARS]
        if not query:
            return []
        [vector] = await self._embedder.embed([query], "RETRIEVAL_QUERY")
        return await self._rpc(query, vector, k, filter_)

    async def _search_many(
        self, queries: list[str], k: int, filters: list[dict[str, str]]
    ) -> list[list[RetrievedChunk]]:
        """Many queries at once: ONE batched embedding call, then parallel DB searches."""
        cleaned = [q.strip()[:MAX_QUERY_CHARS] for q in queries]
        idx = [i for i, q in enumerate(cleaned) if q]
        results: list[list[RetrievedChunk]] = [[] for _ in queries]
        if not idx:
            return results
        vectors = await self._embedder.embed([cleaned[i] for i in idx], "RETRIEVAL_QUERY")
        found = await asyncio.gather(
            *(self._rpc(cleaned[i], v, k, filters[i]) for i, v in zip(idx, vectors, strict=True))
        )
        for i, chunks in zip(idx, found, strict=True):
            results[i] = chunks
        return results

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

    async def search_cv_many(
        self, session_id: UUID, queries: list[str], *, k: int = 3
    ) -> list[list[RetrievedChunk]]:
        f = {"source": "cv", "session_id": str(session_id)}
        return await self._search_many(queries, k, [f] * len(queries))

    async def search_rubric_many(
        self, queries: Sequence[tuple[str, str | None]], *, level: Level | None = None, k: int = 3
    ) -> list[list[RetrievedChunk]]:
        """queries: list of (query_text, competency or None)."""
        filters: list[dict[str, str]] = []
        for _, comp in queries:
            f = {"source": "knowledge"}
            if comp:
                f["competency"] = comp
            if level:
                f["level"] = level
            filters.append(f)
        return await self._search_many([q for q, _ in queries], k, filters)
