"""Knowledge-base loading and idempotent ingestion.

Idempotency: every chunk is identified by the SHA-256 of its content. On each run:
  - chunks whose hash already exists are skipped (no embedding call, no cost),
  - new/changed chunks are embedded in batches and inserted,
  - chunks that no longer exist in the file are deleted.
Running it twice in a row therefore does nothing the second time.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger
from app.db.client import SupabaseRest
from app.services.chunking import Chunk, chunk_markdown, parse_front_matter
from app.services.embeddings import Embedder, to_pgvector

log = get_logger(__name__)

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
VALID_LEVELS = {"junior", "mid"}
URL_RE = re.compile(r"https?://[^\s)>\]]+")


@dataclass(frozen=True)
class KnowledgeFile:
    source_file: str
    competency: str
    title: str
    levels: list[str]
    chunks: list[Chunk]
    resource_urls: list[str]


def load_knowledge_file(path: Path) -> KnowledgeFile:
    meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
    competency = meta.get("competency")
    if not isinstance(competency, str) or not SLUG_RE.match(competency):
        raise ValueError(f"{path.name}: front-matter 'competency' must be a snake_case slug")
    levels = meta.get("levels") or []
    if not isinstance(levels, list) or not levels or not set(levels) <= VALID_LEVELS:
        raise ValueError(f"{path.name}: front-matter 'levels' must be a subset of {VALID_LEVELS}")
    title = str(meta.get("title") or competency.replace("_", " ").title())
    chunks = chunk_markdown(body, title=title)
    if not chunks:
        raise ValueError(f"{path.name}: no content")
    return KnowledgeFile(
        source_file=path.name,
        competency=competency,
        title=title,
        levels=list(levels),
        chunks=chunks,
        resource_urls=URL_RE.findall(body),
    )


def load_knowledge_dir(directory: Path) -> list[KnowledgeFile]:
    files = [load_knowledge_file(p) for p in sorted(directory.glob("*.md"))]
    seen: dict[str, str] = {}
    for f in files:
        if f.competency in seen:
            raise ValueError(
                f"Duplicate competency {f.competency!r} in {seen[f.competency]} and {f.source_file}"
            )
        seen[f.competency] = f.source_file
    return files


@dataclass
class IngestStats:
    files: int = 0
    unchanged: int = 0
    inserted: int = 0
    deleted: int = 0


async def ingest(files: list[KnowledgeFile], db: SupabaseRest, embedder: Embedder) -> IngestStats:
    stats = IngestStats(files=len(files))
    for kf in files:
        existing = await db.select(
            "knowledge_chunks",
            {"select": "id,content_hash", "source_file": f"eq.{kf.source_file}"},
        )
        existing_by_hash = {row["content_hash"]: row["id"] for row in existing}
        wanted = {c.content_hash: c for c in kf.chunks}

        stale_ids = [rid for h, rid in existing_by_hash.items() if h not in wanted]
        new_chunks = [c for h, c in wanted.items() if h not in existing_by_hash]
        stats.unchanged += len(wanted) - len(new_chunks)

        if stale_ids:
            await db.delete("knowledge_chunks", {"id": f"in.({','.join(stale_ids)})"})
            stats.deleted += len(stale_ids)

        if new_chunks:
            vectors = await embedder.embed([c.content for c in new_chunks], "RETRIEVAL_DOCUMENT")
            rows = [
                {
                    "source_file": kf.source_file,
                    "chunk_index": c.index,
                    "competency": kf.competency,
                    "level": c.level,
                    "content": c.content,
                    "content_hash": c.content_hash,
                    "embedding": to_pgvector(v),
                    "metadata": c.metadata,
                }
                for c, v in zip(new_chunks, vectors, strict=True)
            ]
            await db.insert("knowledge_chunks", rows, on_conflict="content_hash")
            stats.inserted += len(rows)

        log.info(
            "knowledge_file_ingested",
            extra={
                "extra_fields": {
                    "file": kf.source_file,
                    "inserted": len(new_chunks),
                    "deleted": len(stale_ids),
                }
            },
        )
    return stats
