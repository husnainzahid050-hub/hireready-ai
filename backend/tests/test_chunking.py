import pytest

from app.services.chunking import chunk_markdown, parse_front_matter

DOC = """---
competency: python
levels: [junior, mid]
---

# Python

## What interviewers evaluate

- Data structures.

## Question bank

### Junior

#### What is a list?

A mutable sequence.

### Mid

#### What is a generator?

A lazy iterator.

```python
# Not a heading inside a code fence
def gen():
    yield 1
```

## Scoring anchors

Anchor text.
"""


def test_front_matter_parsed() -> None:
    meta, body = parse_front_matter(DOC)
    assert meta == {"competency": "python", "levels": ["junior", "mid"]}
    assert body.lstrip().startswith("# Python")


def test_front_matter_missing_returns_empty() -> None:
    meta, body = parse_front_matter("# Title\n\ntext")
    assert meta == {}
    assert body.startswith("# Title")


def test_front_matter_must_be_mapping() -> None:
    with pytest.raises(ValueError):
        parse_front_matter("---\n- a\n- b\n---\nbody")


def test_chunks_follow_headings_and_levels() -> None:
    _, body = parse_front_matter(DOC)
    chunks = chunk_markdown(body, title="Python")
    paths = [c.heading_path for c in chunks]
    assert paths == [
        ["Python", "What interviewers evaluate"],
        ["Python", "Question bank", "Junior", "What is a list?"],
        ["Python", "Question bank", "Mid", "What is a generator?"],
        ["Python", "Scoring anchors"],
    ]
    assert [c.level for c in chunks] == ["all", "junior", "mid", "all"]
    assert [c.index for c in chunks] == [0, 1, 2, 3]


def test_code_fence_comment_is_not_a_heading() -> None:
    _, body = parse_front_matter(DOC)
    gen_chunk = chunk_markdown(body, title="Python")[2]
    assert "# Not a heading inside a code fence" in gen_chunk.body


def test_content_includes_heading_path_and_hash_is_stable() -> None:
    _, body = parse_front_matter(DOC)
    a = chunk_markdown(body, title="Python")
    b = chunk_markdown(body, title="Python")
    assert a[1].content.startswith("Python > Question bank > Junior > What is a list?\n\n")
    assert [c.content_hash for c in a] == [c.content_hash for c in b]
    assert len({c.content_hash for c in a}) == len(a)


def test_long_sections_are_split() -> None:
    para = "word " * 100  # ~500 chars
    body = "## Big\n\n" + "\n\n".join([para] * 5)
    chunks = chunk_markdown(body, title="T", max_chars=1200)
    assert len(chunks) > 1
    assert all(len(c.body) <= 1200 for c in chunks)
    assert all(c.heading_path == ["T", "Big"] for c in chunks)


def test_single_huge_paragraph_is_hard_split() -> None:
    body = "## Big\n\n" + ("x" * 50 + " ") * 100
    chunks = chunk_markdown(body, title="T", max_chars=300)
    assert all(0 < len(c.body) <= 300 for c in chunks)


def test_empty_sections_are_skipped() -> None:
    chunks = chunk_markdown("## A\n\n## B\n\ntext", title="T")
    assert [c.heading_path for c in chunks] == [["T", "B"]]
