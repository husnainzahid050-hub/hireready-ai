"""PDF builders for QA fixtures (no extra dependencies).

`tests/conftest.make_pdf` writes one text line per page. Real CVs have many lines, two-column
layouts, hidden text and image-only (scanned) pages, so these builders place text items at
explicit positions. Text is encoded as WinAnsi (cp1252); characters outside it become "?",
exactly like a cheap PDF exporter would do.
"""

import io
from dataclasses import dataclass

PAGE_W, PAGE_H = 612, 792


@dataclass(frozen=True)
class Item:
    x: float
    y: float
    text: str
    size: float = 10
    white: bool = False  # white-on-white "hidden" text (a classic CV keyword-stuffing trick)


def _pdf_string(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _content(items: list[Item]) -> bytes:
    out = []
    for it in items:
        color = b"1 1 1 rg" if it.white else b"0 0 0 rg"
        out.append(
            color
            + b" BT /F1 "
            + str(it.size).encode()
            + f" Tf {it.x:.1f} {it.y:.1f} Td (".encode()
            + _pdf_string(it.text)
            + b") Tj ET"
        )
    return b"\n".join(out)


def _image_content() -> bytes:
    # 8x8 grey inline image scaled to fill the page: what a scanner produces (pixels, no text).
    pixels = bytes((i * 29) % 256 for i in range(64)).hex().encode()
    return (
        f"q {PAGE_W} 0 0 {PAGE_H} 0 0 cm\n".encode()
        + b"BI /W 8 /H 8 /CS /G /BPC 8 /F /AHx ID\n"
        + pixels
        + b">\nEI Q"
    )


def build_pdf(pages: list[bytes]) -> bytes:
    """Assemble a valid PDF from raw page content streams (shared Helvetica/WinAnsi font)."""
    n = len(pages)
    page_ids = [3 + 2 * i for i in range(n)]
    font_id = 3 + 2 * n
    objs: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{p} 0 R" for p in page_ids).encode()
    objs.append(b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(n).encode() + b" >>")
    for i, stream in enumerate(pages):
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {page_ids[i] + 1} 0 R >>".encode()
        )
        objs.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
    objs.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def lines_pdf(text: str, *, size: float = 10, leading: float = 13) -> bytes:
    """Single-column PDF, paginating automatically."""
    pages: list[list[Item]] = [[]]
    y = PAGE_H - 50
    for line in text.splitlines():
        if y < 50:
            pages.append([])
            y = PAGE_H - 50
        if line.strip():
            pages[-1].append(Item(50, y, line, size))
        y -= leading
    return build_pdf([_content(p) for p in pages])


def two_column_pdf(left: str, right: str, *, size: float = 9, leading: float = 12) -> bytes:
    """Sidebar + main column on one page, items interleaved row by row (as many exporters do)."""
    items: list[Item] = []
    lcol, rcol = left.splitlines(), right.splitlines()
    for row in range(max(len(lcol), len(rcol))):
        y = PAGE_H - 50 - row * leading
        if row < len(lcol) and lcol[row].strip():
            items.append(Item(40, y, lcol[row], size))
        if row < len(rcol) and rcol[row].strip():
            items.append(Item(210, y, rcol[row], size))
    return build_pdf([_content(items)])


def hidden_text_pdf(visible: str, hidden: list[str]) -> bytes:
    """Visible CV plus white-on-white lines at the bottom of page 1."""
    pdf_items: list[Item] = []
    y = PAGE_H - 50
    for line in visible.splitlines():
        if line.strip():
            pdf_items.append(Item(50, y, line))
        y -= 13
    for i, line in enumerate(hidden):
        pdf_items.append(Item(50, 40 + 10 * i, line, 6, white=True))
    return build_pdf([_content(pdf_items)])


def scanned_pdf(pages: int = 1) -> bytes:
    return build_pdf([_image_content() for _ in range(pages)])


def blank_pdf(pages: int = 1) -> bytes:
    return build_pdf([b"" for _ in range(pages)])
