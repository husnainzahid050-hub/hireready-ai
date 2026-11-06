"""Markdown chunking by heading, keeping the heading path as context.

Example: a paragraph under "## Question bank" > "### Junior" > "#### What is a decorator?"
gets heading_path ["Python", "Question bank", "Junior", "What is a decorator?"], and
level "junior". The heading path is prepended to the chunk text so both the
embedding and the full-text index "know" where the chunk came from.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LEVEL_PATTERNS = {"junior": re.compile(r"\bjunior\b", re.I), "mid": re.compile(r"\bmid\b", re.I)}


@dataclass(frozen=True)
class Chunk:
    index: int
    heading_path: list[str]
    body: str
    level: str  # "all" | "junior" | "mid"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content(self) -> str:
        return " > ".join(self.heading_path) + "\n\n" + self.body

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError("Front-matter must be a mapping")
    return meta, text[m.end() :]


def _level_for(path: list[str]) -> str:
    for heading in reversed(path):
        for level, pattern in LEVEL_PATTERNS.items():
            if pattern.search(heading):
                return level
    return "all"


def _split_long(body: str, max_chars: int) -> list[str]:
    if len(body) <= max_chars:
        return [body]
    parts: list[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", body):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            parts.append(current)
        # A single huge paragraph: hard-split on whitespace.
        while len(para) > max_chars:
            cut = para.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            parts.append(para[:cut].strip())
            para = para[cut:].strip()
        current = para
    if current:
        parts.append(current)
    return parts


def chunk_markdown(body: str, *, title: str, max_chars: int = 1500) -> list[Chunk]:
    """Split markdown into heading-scoped chunks. `title` is the root of every path."""
    stack: list[tuple[int, str]] = []  # (heading depth, text)
    buffer: list[str] = []
    sections: list[tuple[list[str], str]] = []
    in_fence = False

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            path = [title] + [h for _, h in stack]
            sections.append((path, text))
        buffer.clear()

    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else HEADING_RE.match(line)
        if m:
            flush()
            depth = len(m.group(1))
            if depth == 1:
                # The H1 is the document title, which is already the path root.
                stack.clear()
                continue
            while stack and stack[-1][0] >= depth:
                stack.pop()
            stack.append((depth, m.group(2).strip()))
        else:
            buffer.append(line)
    flush()

    chunks: list[Chunk] = []
    for path, text in sections:
        for piece in _split_long(text, max_chars):
            chunks.append(
                Chunk(
                    index=len(chunks),
                    heading_path=path,
                    body=piece,
                    level=_level_for(path),
                    metadata={"heading_path": path},
                )
            )
    return chunks
