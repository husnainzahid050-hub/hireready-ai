"""Curated learning resources from the knowledge base: the ONLY URLs the prep plan may use."""

import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.services.knowledge import load_knowledge_dir

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"
LINK_RE = re.compile(r"\[([^\]]+)\]\((https://[^)\s]+)\)")


class Resource(BaseModel):
    competency: str
    title: str
    url: str


@lru_cache
def resource_catalog() -> tuple[Resource, ...]:
    out: list[Resource] = []
    seen: set[str] = set()
    for kf in load_knowledge_dir(KNOWLEDGE_DIR):
        for chunk in kf.chunks:
            if len(chunk.heading_path) > 1 and chunk.heading_path[1] == "Resources":
                for title, url in LINK_RE.findall(chunk.body):
                    if url not in seen:
                        seen.add(url)
                        out.append(Resource(competency=kf.competency, title=title, url=url))
    return tuple(out)


def allowed_urls() -> frozenset[str]:
    return frozenset(r.url for r in resource_catalog())


def resources_for(competencies: set[str]) -> list[Resource]:
    return [r for r in resource_catalog() if r.competency in competencies]
