import io
import zipfile

import pytest

from app.core.errors import AppError
from app.services.parsing import (
    DOCX_MIME,
    MAX_BYTES,
    chunk_cv,
    clean_text,
    detect_kind,
    extract_cv_text,
    validate_jd,
)
from tests.conftest import make_docx, make_pdf

LONG = "Built a retrieval augmented chatbot with FastAPI and LangChain for course PDFs. " * 3


def code_of(exc: pytest.ExceptionInfo[AppError]) -> str:
    return exc.value.code


def test_pdf_text_extracted() -> None:
    text = extract_cv_text(make_pdf([LONG]), "application/pdf")
    assert "FastAPI" in text


def test_docx_text_extracted() -> None:
    text = extract_cv_text(make_docx(["ALI RAZA", LONG]), DOCX_MIME)
    assert text.startswith("ALI RAZA") and "LangChain" in text


def test_magic_bytes_beat_a_lying_extension() -> None:
    with pytest.raises(AppError) as exc:
        extract_cv_text(b"MZ\x90\x00" + b"x" * 500, "application/pdf")  # a Windows .exe header
    assert code_of(exc) == "unsupported_file"


def test_mime_mismatch_rejected() -> None:
    with pytest.raises(AppError) as exc:
        detect_kind(make_pdf([LONG]), "image/png")
    assert code_of(exc) == "unsupported_file"


def test_too_many_pages_rejected() -> None:
    with pytest.raises(AppError) as exc:
        extract_cv_text(make_pdf([LONG] * 6), "application/pdf")
    assert code_of(exc) == "too_many_pages"


def test_scanned_or_empty_pdf_gives_helpful_error() -> None:
    with pytest.raises(AppError) as exc:
        extract_cv_text(make_pdf([""]), "application/pdf")
    assert code_of(exc) == "no_text"
    assert "scanned" in exc.value.message


def test_size_limit() -> None:
    with pytest.raises(AppError) as exc:
        extract_cv_text(b"%PDF-" + b"0" * MAX_BYTES, "application/pdf")
    assert code_of(exc) == "file_too_large" and exc.value.status_code == 413


def test_empty_file() -> None:
    with pytest.raises(AppError) as exc:
        extract_cv_text(b"", "application/pdf")
    assert code_of(exc) == "empty_file"


def test_zip_that_is_not_docx_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "hi")
    with pytest.raises(AppError) as exc:
        extract_cv_text(buf.getvalue(), DOCX_MIME)
    assert code_of(exc) == "unsupported_file"


def test_docx_zip_bomb_guard() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", "<w/>")
        zf.writestr("word/huge.bin", b"\0" * (26 * 1024 * 1024))  # compresses to ~25 KB
    data = buf.getvalue()
    assert len(data) < MAX_BYTES
    with pytest.raises(AppError) as exc:
        extract_cv_text(data, DOCX_MIME)
    assert code_of(exc) == "invalid_file"


def test_validate_jd_limits() -> None:
    with pytest.raises(AppError, match="at least"):
        validate_jd("short")
    with pytest.raises(AppError, match="at most"):
        validate_jd("x" * 8001)
    assert validate_jd("  " + "y" * 300 + "  ") == "y" * 300


def test_clean_text_collapses_whitespace() -> None:
    assert clean_text("a \t  b\n\n\n\nc\x00") == "a b\n\nc"


def test_chunk_cv_keeps_lines_and_bounds_size() -> None:
    lines = [f"- bullet number {i} " + "x" * 60 for i in range(40)]
    chunks = chunk_cv("\n".join(lines), max_chars=300)
    assert all(len(c) <= 300 for c in chunks)
    assert "\n".join(chunks).count("- bullet number") == 40
