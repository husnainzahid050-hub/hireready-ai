"""Run sample hybrid-search queries against the ingested knowledge base.

Usage (from backend/, after ingestion):
    python -m scripts.search_demo
    python -m scripts.search_demo "how do I explain overfitting" --competency machine_learning
"""

import argparse
import asyncio

from app.core.http import close_http_client
from app.db.client import get_db
from app.services.embeddings import get_embedder
from app.services.retrieval import Retriever

SAMPLES = [
    ("What does a strong answer about Python decorators include?", None),
    ("How to explain the bias-variance tradeoff", None),
    ("RAG retrieval augmented generation chunking embeddings", None),
    ("Tell me about a time you had a conflict in a team", None),
    ("SQL window functions vs GROUP BY", "sql"),
]


async def main(query: str | None, competency: str | None) -> None:
    retriever = Retriever(get_db(), get_embedder())
    queries = [(query, competency)] if query else SAMPLES
    try:
        for q, comp in queries:
            print(f"\n=== {q}" + (f"  [competency={comp}]" if comp else ""))
            for r in await retriever.search_rubric(q, competency=comp, k=5):
                first_line = r.content.splitlines()[0]
                print(f"  {r.score:.4f}  {r.competency:<18} {r.level:<6} {first_line[:90]}")
    finally:
        await close_http_client()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("query", nargs="?")
    p.add_argument("--competency")
    a = p.parse_args()
    asyncio.run(main(a.query, a.competency))
