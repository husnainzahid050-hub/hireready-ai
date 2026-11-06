"""CV upload validation and text extraction (PDF / DOCX only).

Checks, in order: size -> declared MIME type -> magic bytes (the real file signature, since
a client can lie about MIME) -> structure (page count, zip bomb guard) -> extracted text.
Files are parsed in memory and never stored or executed; only the extracted text is kept.

Parser DoS hardening: a 2 MB file can still decompress to gigabytes or contain millions of
objects. pypdf runs with tight resource limits (`PDF_LIMITS`, external `jbig2dec` disabled),
DOCX archives are checked for unpacked size and entry count, and the async entrypoint runs
parsing in a worker thread with a wall-clock timeout so one hostile file can't freeze the
event loop for other requests.
"""

import asyncio
import io
import re
import zipfile
from typing import Literal

from app.core.errors import AppError

MAX_BYTES = 2 * 1024 * 1024
MAX_PDF_PAGES = 5
MAX_CV_CHARS = 30_000
MAX_DOCX_UNCOMPRESSED = 25 * 1024 * 1024
MAX_DOCX_ENTRIES = 500  # a real CV .docx has ~10-40 parts
PARSE_TIMEOUT_S = 15.0
_MB = 1024 * 1024
# Overrides for pypdf.Configuration (defaults are ~75 MB per stream; a 5-page CV needs far less).
PDF_LIMITS: dict[str, object] = {
    "maximum_declared_stream_length": 20 * _MB,
    "zlib_maximum_output_length": 20 * _MB,
    "lzw_maximum_output_length": 20 * _MB,
    "run_length_maximum_output_length": 20 * _MB,
    "brotli_maximum_output_length": 20 * _MB,
    "array_based_stream_maximum_output_length": 20 * _MB,
    "jbig2_maximum_output_length": 20 * _MB,
    "image_maximum_buffer_size": 20 * _MB,
    "stream_decoding_work_maximum_length": 60 * _MB,
    "page_tree_maximum_entries": 1_000,
    "outline_maximum_entries": 1_000,
    "form_fields_maximum_entries": 1_000,
    "xform_maximum_invocations_per_extraction": 500,
    "jbig2dec_binary": None,  # never spawn an external decoder on untrusted input
}
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
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _pdf_text(data: bytes) -> str:
    # lazy import: keeps cold start fast for other endpoints
    from pypdf import PdfReader, apply_configuration, get_configuration

    try:
        with apply_configuration(get_configuration().with_overwrites(**PDF_LIMITS)):
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise _bad(
                    "encrypted_pdf",
                    "This PDF is password-protected. Please upload an unlocked copy.",
                )
            if len(reader.pages) > MAX_PDF_PAGES:
                raise _bad("too_many_pages", f"Your CV must be at most {MAX_PDF_PAGES} pages.")
            parts: list[str] = []
            size = 0
            for page in reader.pages:
                text = page.extract_text() or ""
                parts.append(text)
                size += len(text)
                if size > MAX_CV_CHARS:  # we only keep MAX_CV_CHARS anyway
                    break
            return "\n".join(parts)
    except AppError:
        raise
    except Exception as exc:  # PyPdfError/LimitReachedError, and KeyError/ValueError/... on junk
        raise _bad("invalid_file", "We couldn't read this PDF. Try re-exporting it.") from exc


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                raise _bad("unsupported_file", "Please upload your CV as a PDF or DOCX file.")
            infos = zf.infolist()
            if len(infos) > MAX_DOCX_ENTRIES:
                raise _bad("invalid_file", "This DOCX file has too many parts.")
            # file_size comes from the archive header; zipfile never inflates past it, so a
            # lying header can't produce more output than we checked here.
            if sum(i.file_size for i in infos) > MAX_DOCX_UNCOMPRESSED:
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


async def extract_cv_text_async(
    data: bytes, content_type: str | None, timeout_s: float = PARSE_TIMEOUT_S
) -> str:
    """`extract_cv_text` off the event loop, with a wall-clock timeout.

    Note: Python can't kill a thread, so a timed-out parse keeps running in the background
    until pypdf's own limits stop it; the request still gets a fast, clear error.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(extract_cv_text, data, content_type), timeout_s
        )
    except TimeoutError as exc:
        raise _bad(
            "parse_timeout", "This file took too long to read. Try re-exporting it as a PDF.", 422
        ) from exc


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
