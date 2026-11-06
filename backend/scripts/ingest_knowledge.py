"""Ingest backend/knowledge/*.md into the knowledge_chunks table.

Usage (from backend/):
    python -m scripts.ingest_knowledge --dry-run     # validate + show chunk stats, no network
    python -m scripts.ingest_knowledge               # embed new chunks and upsert
"""

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

from app.core.http import close_http_client
from app.core.logging import configure_logging
from app.db.client import get_db
from app.services.embeddings import get_embedder
from app.services.knowledge import ingest, load_knowledge_dir

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"


async def main(dry_run: bool) -> int:
    files = load_knowledge_dir(KNOWLEDGE_DIR)
    total = sum(len(f.chunks) for f in files)
    print(f"Loaded {len(files)} files, {total} chunks")
    for f in files:
        levels = Counter(c.level for c in f.chunks)
        print(f"  {f.source_file:<28} {f.competency:<20} chunks={len(f.chunks):<3} {dict(levels)}")
    if dry_run:
        return 0

    configure_logging()
    try:
        stats = await ingest(files, get_db(), get_embedder())
    finally:
        await close_http_client()
    print(f"Done: inserted={stats.inserted} unchanged={stats.unchanged} deleted={stats.deleted}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Parse and validate only")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.dry_run)))
