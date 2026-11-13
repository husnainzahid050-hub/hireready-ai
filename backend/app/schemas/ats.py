"""ATS readiness: file signals (collected at upload) and the scored report (computed at analysis).

Nothing here is LLM output, so defaults are fine. Storage needs no migration:
- `FileSignals` lives inside the CV's `documents.structured` JSON under `ats_file` (the file itself
  is never stored; the analysis merges the extracted profile next to it instead of overwriting);
- `AtsReport` lives inside `gap_analyses.breakdown` under `ats`, so `copy_demo_analysis` (which
  copies `breakdown`) carries it to cached demo sessions for free.
"""

from typing import Literal

from pydantic import BaseModel, Field

FileKind = Literal["pdf", "docx", "text"]
CheckStatus = Literal["pass", "warn", "fail", "info"]
AtsCategoryId = Literal["readability", "keywords", "content"]
KeywordStatus = Literal["exact", "alias_only", "missing"]
KeywordImportance = Literal["must_have", "nice_to_have", "title", "credential"]

MAX_SAMPLES = 3
SAMPLE_CHARS = 80


class FileSignals(BaseModel):
    """Layout facts only the original file can tell. Summaries only: no coordinates kept."""

    kind: FileKind
    pages: int | None = None
    page_chars: list[int] = Field(default_factory=list)  # extracted characters per page
    page_images: list[int] = Field(default_factory=list)  # images per page (PDF)
    multi_column_pages: int = 0  # PDF pages whose text sits in 2+ side-by-side columns
    docx_columns: int = 1  # most columns set on any DOCX section (w:cols)
    table_count: int = 0
    table_chars: int = 0  # characters inside DOCX tables
    body_chars: int = 0  # characters in the DOCX body (paragraphs + tables)
    textbox_count: int = 0
    textbox_chars: int = 0  # DOCX text-box text: python-docx and many ATS parsers skip it
    header_footer_chars: int = 0  # DOCX header/footer text: many ATS parsers skip it
    # email / phone found ONLY in a header, footer or text box (not in the page body)
    contact_outside_body: Literal["header_footer", "text_box"] | None = None
    lost_samples: list[str] = Field(default_factory=list)  # first words of that skipped text
    image_count: int = 0
    light_text_chars: int = 0  # PDF white / near-white text (hidden keywords or a dark sidebar)
    generic_file_name: bool = False  # "final_v3.pdf", "resume.docx", "scan001.pdf"


class AtsCheck(BaseModel):
    id: str  # R1..R8, K1..K5, C1..C6, I-* (info)
    category: AtsCategoryId
    title: str
    status: CheckStatus
    weight: float  # within its category; 0 for info / dropped checks
    points: float  # 1 pass, 0.5 warn, 0 fail (K1/K2: continuous share)
    message: str  # what we found
    fix: str | None  # what to do (None when it passes)
    evidence: str | None  # the line or term behind it, quoted from the CV


class KeywordHit(BaseModel):
    term: str  # the job's wording
    importance: KeywordImportance
    status: KeywordStatus
    matched_as: str | None  # the CV's wording (alias or variant actually found)
    count: int  # times in the CV (shown; never more credit for repeating it)
    jd_count: int
    sections: list[str]  # CV sections it appears in: skills / experience / projects / ...
    proven_not_searchable: bool = False  # verified evidence, but not the job's words
    evidence_quote: str | None = None  # that verified CV quote
    where_to_add: str | None = None


class AtsComponent(BaseModel):
    """Same shape as the match score's ScoreComponent (the UI reuses its bar)."""

    weight: float
    score: float  # 0-1
    detail: str


class AtsReport(BaseModel):
    score: int
    band: Literal["ready", "few_fixes", "fix_first"]
    band_label: str
    formula: str
    gated: bool  # no reliable text: capped
    readability: AtsComponent
    keywords: AtsComponent
    content: AtsComponent
    checks: list[AtsCheck]
    keyword_hits: list[KeywordHit]
    knockouts: list[str]  # hard requirements the JD states (screening questions)
    file_kind: FileKind
    version: int = 1
