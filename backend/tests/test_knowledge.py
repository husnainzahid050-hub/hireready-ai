from pathlib import Path

import pytest

from app.services.knowledge import ingest, load_knowledge_dir, load_knowledge_file
from tests.fakes import FakeDB, FakeEmbedder

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

REQUIRED_COMPETENCIES = {
    "python", "sql", "machine_learning", "deep_learning", "nlp_llms", "data_handling",
    "apis_backend", "frontend_basics", "git_collaboration", "cloud_devops", "system_design",
    "behavioral", "communication", "problem_solving",
}  # fmt: skip


# ---------- content checks on the real knowledge base ----------


@pytest.fixture(scope="module")
def kb():  # type: ignore[no-untyped-def]
    return load_knowledge_dir(KNOWLEDGE_DIR)


def test_all_required_competencies_present(kb) -> None:  # type: ignore[no-untyped-def]
    assert {f.competency for f in kb} >= REQUIRED_COMPETENCIES


@pytest.mark.parametrize(
    "section", ["What interviewers evaluate", "Question bank", "Scoring anchors", "Resources"]
)
def test_every_file_has_required_sections(kb, section: str) -> None:  # type: ignore[no-untyped-def]
    for f in kb:
        top_level = {c.heading_path[1] for c in f.chunks if len(c.heading_path) > 1}
        assert section in top_level, f"{f.source_file} missing '{section}'"


def test_every_file_has_junior_and_mid_questions_and_1_3_5_anchors(kb) -> None:  # type: ignore[no-untyped-def]
    for f in kb:
        levels = {c.level for c in f.chunks}
        assert {"junior", "mid"} <= levels, f.source_file
        anchors = " ".join(c.content for c in f.chunks if c.heading_path[1] == "Scoring anchors")
        for score in ("1/5", "3/5", "5/5"):
            assert score in anchors, f"{f.source_file} missing anchor {score}"


def test_resources_are_https_and_present(kb) -> None:  # type: ignore[no-untyped-def]
    for f in kb:
        assert f.resource_urls, f.source_file
        assert all(u.startswith("https://") for u in f.resource_urls), f.source_file


def test_chunks_fit_embedding_budget(kb) -> None:  # type: ignore[no-untyped-def]
    for f in kb:
        assert all(len(c.content) < 8000 for c in f.chunks)


def test_invalid_front_matter_rejected(tmp_path: Path) -> None:
    p = tmp_path / "bad.md"
    p.write_text(
        "---\ncompetency: Bad Name\nlevels: [junior]\n---\n# X\n\n## A\n\ntext\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="snake_case"):
        load_knowledge_file(p)
    p.write_text(
        "---\ncompetency: ok\nlevels: [senior]\n---\n# X\n\n## A\n\ntext\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="levels"):
        load_knowledge_file(p)


def test_duplicate_competency_rejected(tmp_path: Path) -> None:
    for name in ("a.md", "b.md"):
        (tmp_path / name).write_text(
            "---\ncompetency: same\nlevels: [junior]\n---\n## A\n\nx\n", encoding="utf-8"
        )
    with pytest.raises(ValueError, match="Duplicate"):
        load_knowledge_dir(tmp_path)


# ---------- idempotent ingestion with an in-memory fake DB ----------


def embedded(emb: FakeEmbedder) -> int:
    assert all(task == "RETRIEVAL_DOCUMENT" for _, task in emb.calls)
    return sum(len(texts) for texts, _ in emb.calls)


def write_kb(directory: Path, extra: str = "") -> None:
    (directory / "x.md").write_text(
        "---\ncompetency: x\nlevels: [junior]\n---\n# X\n\n## Intro\n\nHello.\n\n"
        "## Question bank\n\n### Junior\n\n#### Q1\n\nAnswer one.\n" + extra,
        encoding="utf-8",
    )


async def test_ingest_is_idempotent_and_handles_changes(tmp_path: Path) -> None:
    db, emb = FakeDB(), FakeEmbedder()

    write_kb(tmp_path)
    s1 = await ingest(load_knowledge_dir(tmp_path), db, emb)  # type: ignore[arg-type]
    assert (s1.inserted, s1.unchanged, s1.deleted) == (2, 0, 0)
    assert {r["level"] for r in db.rows("knowledge_chunks")} == {"all", "junior"}
    assert all(r["embedding"].startswith("[") for r in db.rows("knowledge_chunks"))

    # Second run: nothing to do, no embedding calls.
    s2 = await ingest(load_knowledge_dir(tmp_path), db, emb)  # type: ignore[arg-type]
    assert (s2.inserted, s2.unchanged, s2.deleted) == (0, 2, 0)
    assert embedded(emb) == 2

    # Edit one section and add another: only changed/new chunks are embedded; stale one deleted.
    (tmp_path / "x.md").write_text(
        "---\ncompetency: x\nlevels: [junior]\n---\n# X\n\n## Intro\n\nHello, edited.\n\n"
        "## Question bank\n\n### Junior\n\n#### Q1\n\nAnswer one.\n\n## Resources\n\n- https://example.org\n",
        encoding="utf-8",
    )
    s3 = await ingest(load_knowledge_dir(tmp_path), db, emb)  # type: ignore[arg-type]
    assert (s3.inserted, s3.unchanged, s3.deleted) == (2, 1, 1)
    assert len(db.rows("knowledge_chunks")) == 3
    assert embedded(emb) == 4
