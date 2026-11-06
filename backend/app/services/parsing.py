"""CV upload validation and text extraction (PDF / DOCX only).

Checks, in order: size -> declared MIME type -> magic bytes (the real file signature, since
a client can lie about MIME) -> structure (page count, zip bomb guard) -> extracted text.
Files are parsed in memory and never stored or executed; only the extracted text is kept.
"""

import io
import re
import unicodedata
import zipfile
from typing import Literal

from app.core.errors import AppError

MAX_BYTES = 2 * 1024 * 1024
MAX_PDF_PAGES = 5
MAX_CV_CHARS = 30_000
MAX_DOCX_UNCOMPRESSED = 25 * 1024 * 1024
JD_MIN_CHARS, JD_MAX_CHARS = 200, 8_000

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FileKind = Literal["pdf", "docx"]


def _bad(code: str, message: str, status: int = 400) -> AppError:
    return AppError(code, message, status_code=status)


def detect_kind(data: bytes, content_type: str | None) -> FileKind:
    ct = (content_type or "").split(";")[0].strip().lower()
    if data.startswith(b"%PDF-"):
        if ct and ct not in (PDF_MIME, "application/octet-stream"):
            raise _bad("unsupported_file", "File type does not match its contents.")
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        if ct and ct not in (DOCX_MIME, "application/octet-stream", "application/zip"):
            raise _bad("unsupported_file", "File type does not match its contents.")
        return "docx"
    raise _bad("unsupported_file", "Please upload your CV as a PDF or DOCX file.")


def clean_text(text: str) -> str:
    # NFKC folds PDF ligatures ("ﬁ" -> "fi", common in LaTeX/Chrome exports) and Arabic-script
    # presentation forms back to normal letters, so keyword search and the LLM see real words.
    text = unicodedata.normalize("NFKC", text).replace("\x00", "")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader  # lazy import: keeps cold start fast for other endpoints
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise _bad(
                "encrypted_pdf", "This PDF is password-protected. Please upload an unlocked copy."
            )
        if len(reader.pages) > MAX_PDF_PAGES:
            raise _bad("too_many_pages", f"Your CV must be at most {MAX_PDF_PAGES} pages.")
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except PdfReadError as exc:
        raise _bad("invalid_file", "We couldn't read this PDF. Try re-exporting it.") from exc


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                raise _bad("unsupported_file", "Please upload your CV as a PDF or DOCX file.")
            if sum(i.file_size for i in zf.infolist()) > MAX_DOCX_UNCOMPRESSED:
                raise _bad("invalid_file", "This DOCX file is too large when unpacked.")
    except zipfile.BadZipFile as exc:
        raise _bad("invalid_file", "We couldn't read this DOCX file.") from exc

    from docx import Document  # lazy import

    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:  # python-docx raises a variety of errors on bad files
        raise _bad("invalid_file", "We couldn't read this DOCX file.") from exc
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def extract_cv_text(data: bytes, content_type: str | None) -> str:
    if not data:
        raise _bad("empty_file", "The uploaded file is empty.")
    if len(data) > MAX_BYTES:
        raise _bad("file_too_large", "Your CV must be 2 MB or smaller.", 413)
    kind = detect_kind(data, content_type)
    raw = _pdf_text(data) if kind == "pdf" else _docx_text(data)
    text = clean_text(raw)
    if len(text) < 100:
        raise _bad(
            "no_text",
            "We couldn't find text in this file. If it's a scanned PDF, please upload a "
            "text-based PDF (exported from Word or Google Docs).",
        )
    return text[:MAX_CV_CHARS]


def validate_jd(text: str) -> str:
    text = clean_text(text or "")
    if len(text) < JD_MIN_CHARS:
        raise _bad(
            "jd_too_short",
            f"Please paste the full job description (at least {JD_MIN_CHARS} characters).",
        )
    if len(text) > JD_MAX_CHARS:
        raise _bad("jd_too_long", f"The job description must be at most {JD_MAX_CHARS} characters.")
    return text


def chunk_cv(text: str, max_chars: int = 700) -> list[str]:
    """Group CV lines into ~700-char chunks along line boundaries (keeps bullets intact)."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in (ln.strip() for ln in text.splitlines()):
        if not line:
            continue
        if size + len(line) > max_chars and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        while len(line) > max_chars:  # extremely long single line
            chunks.append(line[:max_chars])
            line = line[max_chars:]
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks
