"""Layout signals for the ATS check, collected while the CV file is parsed (it is never stored).

Real ATS parsers (Workday, Taleo, Greenhouse, Lever, ...) read a CV top to bottom as plain text.
What breaks them is layout the plain text can't show: side-by-side columns (lines from both
columns get merged), text boxes and page headers (often skipped), tables, and scanned pages.

PDF: `PdfPageProbe` receives every text run pypdf extracts, with its position and the current
fill colour, so the checks need no second pass over the file. Column detection is a heuristic:
two clusters of line starts, far apart, both tall, the right one not just dates (a right-aligned
"Jun 2024 - Present" is a normal single-column layout).

DOCX: a few regex counts over the XML parts we already opened (the archive is size-checked first).
"""

import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.schemas.ats import MAX_SAMPLES, SAMPLE_CHARS, FileSignals

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{7,}\d(?![\w.])")
DATE_TOKEN = re.compile(
    r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|present|current|"
    r"(?:19|20)\d{2})\b"
)

X_BUCKET = 6.0  # points; line starts within this distance share a cluster
MIN_COLUMN_LINES = 4
MIN_COLUMN_GAP = 0.25  # of the page width
MIN_RIGHT_CHARS = 25
LIGHT = 0.9  # fill colour components at or above this (RGB/grey) count as "near white"


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class PdfPageProbe:
    """pypdf visitor callbacks for one page."""

    def __init__(self, width: float) -> None:
        self.width = width or 612.0
        self.light = False
        self.light_chars = 0
        self.inline_images = 0
        self.runs: list[tuple[float, float, str]] = []  # (x, y, text) of runs that start a line

    def on_operator(self, op: bytes, args: list[Any], cm: list[float], tm: list[float]) -> None:
        if op in (b"rg", b"g", b"sc", b"scn") and args:
            vals = [n for n in (_num(a) for a in args) if n is not None]
            if vals:
                self.light = all(v >= LIGHT for v in vals)
        elif op == b"k" and len(args) == 4:
            vals = [_num(a) or 0.0 for a in args]
            self.light = all(v <= 1 - LIGHT for v in vals)
        elif op == b"INLINE IMAGE":
            self.inline_images += 1

    def on_text(self, text: str, cm: list[float], tm: list[float], font: Any, size: float) -> None:
        stripped = text.strip()
        if not stripped:
            return
        if self.light:
            self.light_chars += len(stripped)
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        self.runs.append((x, y, stripped))

    def columns(self) -> int:
        """2 when the page looks like side-by-side columns, else 1.

        Two clusters of line starts at least 25% of the page width apart, each with 4+ lines,
        whose vertical extents overlap by half. Right-hand runs that are dates or shorter than
        25 characters are ignored, so right-aligned "Jun 2024 - Present" / "Lahore" lines on a
        single-column CV are not mistaken for a second column.
        """
        starts = Counter(round(x / X_BUCKET) for x, _, _ in self.runs)
        lefts = [b for b, n in starts.items() if n >= MIN_COLUMN_LINES]
        if not lefts:
            return 1
        left = min(lefts)
        content = [
            (x, y)
            for x, y, t in self.runs
            if len(t) >= MIN_RIGHT_CHARS and not (len(t) <= 40 and DATE_TOKEN.search(t))
        ]
        rights = Counter(round(x / X_BUCKET) for x, _ in content)
        lys = [y for x, y, _ in self.runs if round(x / X_BUCKET) == left]
        for right, n in rights.items():
            if n < MIN_COLUMN_LINES or (right - left) * X_BUCKET < MIN_COLUMN_GAP * self.width:
                continue
            rys = [y for x, y in content if round(x / X_BUCKET) == right]
            overlap = min(max(lys), max(rys)) - max(min(lys), min(rys))
            span = min(max(lys) - min(lys), max(rys) - min(rys))
            if span > 0 and overlap >= 0.5 * span:
                return 2
        return 1

    def add_to(self, signals: FileSignals, page: Any, chars: int) -> None:
        images = self.inline_images + _xobject_images(page)
        signals.page_chars.append(chars)
        signals.page_images.append(images)
        signals.light_text_chars += self.light_chars
        signals.image_count += images
        if self.columns() > 1:
            signals.multi_column_pages += 1


def _xobject_images(page: Any) -> int:
    try:
        found: Any = page["/Resources"].get("/XObject")
        xobjects: Any = found.get_object() if found is not None else {}
        return sum(1 for v in xobjects.values() if v.get_object().get("/Subtype") == "/Image")
    except Exception:  # odd resource trees: counting images is best-effort
        return 0


# ------------------------------------------------------------------ DOCX

_W_TEXT = re.compile(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>")
_TEXTBOX = re.compile(r"<w:txbxContent\b(.*?)</w:txbxContent>", re.S)
_COLS = re.compile(r"<w:cols\b[^>]*\bw:num=\"(\d+)\"")
_PICTURE = re.compile(r"<pic:pic\b|<v:imagedata\b")


def _xml_text(xml: str) -> str:
    return " ".join(_W_TEXT.findall(xml))


@dataclass
class DocxExtras:
    """Text python-docx's `doc.paragraphs` never returns, plus the layout counts."""

    signals: FileSignals
    header: str
    footer: str
    textboxes: list[str]


def _part_text(zf: zipfile.ZipFile, pattern: str) -> str:
    names = sorted(n for n in zf.namelist() if re.fullmatch(pattern, n))
    texts = (_xml_text(zf.read(n).decode("utf-8", errors="replace")).strip() for n in names)
    return "\n".join(dict.fromkeys(t for t in texts if t))  # first/even/odd pages often repeat


def docx_signals(zf: zipfile.ZipFile) -> DocxExtras:
    """Counts and skipped text from the already size-checked archive (tables: the caller)."""
    signals = FileSignals(kind="docx")
    body = zf.read("word/document.xml").decode("utf-8", errors="replace")
    # Word writes each text box twice (a modern shape plus a VML fallback): keep unique texts.
    boxes = list(
        dict.fromkeys(t for t in (_xml_text(b).strip() for b in _TEXTBOX.findall(body)) if t)
    )
    signals.textbox_count = len(boxes)
    signals.textbox_chars = sum(len(t) for t in boxes)
    signals.docx_columns = max([int(n) for n in _COLS.findall(body)] or [1])
    signals.image_count = len(_PICTURE.findall(body))
    header = _part_text(zf, r"word/header\d*\.xml")
    footer = _part_text(zf, r"word/footer\d*\.xml")
    signals.header_footer_chars = len(header) + len(footer)
    main_text = _xml_text(_TEXTBOX.sub(" ", body))
    for where, text in (("header_footer", header + " " + footer), ("text_box", " ".join(boxes))):
        for rx in (EMAIL_RE, PHONE_RE):
            found = rx.search(text)
            if found and found.group(0) not in main_text and signals.contact_outside_body is None:
                signals.contact_outside_body = where  # type: ignore[assignment]
    samples = [t for t in (header, footer, *boxes) if t]
    signals.lost_samples = [t[:SAMPLE_CHARS] for t in samples[:MAX_SAMPLES]]
    return DocxExtras(signals, header, footer, boxes)


_GENERIC_NAME = re.compile(
    r"(?i)^(?:(?:my[_ -]?)?(?:cv|resume|résumé|document|untitled|scan|final|new|draft|file|"
    r"image|img|doc)[\W_]*(?:v?\d+|final|new|copy|updated|latest)?[\W_]*)+$"
)


def generic_file_name(filename: str | None) -> bool:
    """'final_v3.pdf' / 'resume.docx' / 'scan001.pdf' say nothing; 'Ali_Raza_CV.pdf' does."""
    if not filename:
        return False
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
    return bool(_GENERIC_NAME.match(stem)) or bool(re.fullmatch(r"[\W\d_]+", stem))
