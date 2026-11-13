"""ATS readiness: will an Applicant Tracking System read this CV cleanly, and would a recruiter's
keyword search for this job find it? Pure functions: no LLM, no I/O, same input -> same report.

    ATS readiness = 100 x (0.40 x readability + 0.45 x keyword coverage + 0.15 content quality)

Each check is pass / warn / fail (1 / 0.5 / 0 points; K1 and K2 use the continuous share of terms
found). A category is the weighted mean of its scored checks; checks that don't apply are dropped
and the rest renormalised. If R1 or R2 fails (no reliable text) the total is capped at 40.

Inputs: the extracted CV text, the layout `FileSignals` collected at upload (services/layout.py),
the CV / job profiles (cached, so the keyword list is stable) and the skill verdicts (for the
"proven but not searchable" overlay, which is shown but not scored).

What this models: how parsers (Greenhouse, Workday, Lever, Taleo, ...) turn a file into fields,
and how recruiters then search by keyword and job title. It is NOT any vendor's private ranking,
and ATSs mostly don't auto-reject on CV format: knockout questions do (the knockout panel).
Spec: research brief ATS_BRIEF.md section 3; deviations are listed in CHANGELOG.md.
"""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from app.core.injection import looks_like_injection
from app.schemas.analysis import CVProfile, GapItem, JobProfile, Seniority
from app.schemas.ats import (
    AtsCategoryId,
    AtsCheck,
    AtsComponent,
    AtsReport,
    CheckStatus,
    FileSignals,
    KeywordHit,
    KeywordImportance,
    KeywordStatus,
)
from app.services.evidence import normalize
from app.services.layout import EMAIL_RE, PHONE_RE

ALIASES_FILE = Path(__file__).resolve().parents[2] / "knowledge" / "aliases.yaml"

# The demo CV is pasted text: score it as a clean, single-column, text-based file.
SAMPLE_SIGNALS = FileSignals(kind="text", pages=1)

WEIGHTS: dict[AtsCategoryId, float] = {"readability": 0.40, "keywords": 0.45, "content": 0.15}
GATE_CAP = 40
GATE_CHECKS = ("R1", "R2")
BANDS: tuple[tuple[int, Literal["ready", "few_fixes", "fix_first"], str], ...] = (
    (80, "ready", "Ready to submit"),
    (60, "few_fixes", "A few fixes"),
    (0, "fix_first", "Fix before applying"),
)
FORMULA = (
    "ATS readiness = 100 x (0.40 x readability + 0.45 x keyword coverage + 0.15 x content "
    "quality); check points: pass 1, warn 0.5, fail 0 (keywords: share of the job's terms found, "
    "exact 1, alias only 0.5); checks that don't apply are dropped and the rest renormalised; "
    f"capped at {GATE_CAP} when the CV has no reliable text (R1 or R2 fails)"
)
_POINTS: dict[CheckStatus, float] = {"pass": 1.0, "warn": 0.5, "fail": 0.0, "info": 0.0}
TERM_POINTS: dict[KeywordStatus, float] = {"exact": 1.0, "alias_only": 0.5, "missing": 0.0}

# ------------------------------------------------------------------ text matching


def mnorm(text: str) -> str:
    """evidence.normalize plus hyphen = space ('scikit-learn' == 'scikit learn') and no dot
    inside a word ('node.js' == 'nodejs'; '.net' keeps its leading dot)."""
    text = re.sub(r"(?<=[a-z0-9])-(?=[a-z0-9])", " ", normalize(text))
    return re.sub(r"(?<=[a-z0-9])\.(?=[a-z])", "", text)


def _term_re(term: str) -> re.Pattern[str]:
    # Token boundaries that respect tech symbols: c++, c#, .net, node.js; "r" not inside "react".
    return re.compile(r"(?<![a-z0-9+#])" + re.escape(term) + r"(?![a-z0-9+#])")


def count_in(term: str, normalized_text: str) -> int:
    t = mnorm(term)
    return len(_term_re(t).findall(normalized_text)) if t else 0


def variants(term: str) -> list[str]:
    """Spellings that count as EXACT: dotted (node.js = nodejs), plural / -ing / -ed on the last
    token for terms of 5+ characters."""
    t = mnorm(term)
    out = [t]
    if re.fullmatch(
        r"[a-z]+", t
    ):  # React = React.js = ReactJS ("react.js" normalises to "reactjs")
        out.append(t[:-2] if t.endswith("js") and len(t) > 4 else t + "js")
    words = t.split()
    if len(t) >= 5 and words and words[-1].isalpha():
        last, head = words[-1], " ".join(words[:-1])
        forms = {last + "s", last + "es", last + "ing", last + "ed"}
        for suffix in ("ies", "es", "s", "ing", "ed"):
            if last.endswith(suffix) and len(last) - len(suffix) >= 3:
                stem = last[: -len(suffix)]
                forms |= {stem, stem + "s", stem + "e", stem + "es"}
                if suffix == "ies":
                    forms.add(stem + "y")
        if last.endswith("e"):
            forms |= {last[:-1] + "ing", last + "d"}
        out += [f"{head} {f}".strip() for f in sorted(forms)]
    return list(dict.fromkeys(out))


@lru_cache
def alias_groups() -> tuple[frozenset[str], ...]:
    data = yaml.safe_load(ALIASES_FILE.read_text(encoding="utf-8")) or {}
    return tuple(
        frozenset(mnorm(str(x)) for x in [name, *(others or [])]) for name, others in data.items()
    )


def aliases_of(term: str) -> list[str]:
    forms = set(variants(term))
    out: list[str] = []
    for group in alias_groups():
        if forms & group:
            out += sorted(group - forms)
    return list(dict.fromkeys(out))


def _short_upper(alias: str) -> bool:
    # "AI", "ML", "UI", "REST": only count the all-caps form, so "rest of", "ui" in a word, ...
    return alias.isalpha() and len(alias) <= 4


def count_alias(alias: str, normalized: str, raw: str) -> int:
    if _short_upper(alias):
        return len(
            re.findall(r"(?<![A-Za-z0-9+#])" + re.escape(alias.upper()) + r"(?![A-Za-z0-9+#])", raw)
        )
    return count_in(alias, normalized)


@dataclass(frozen=True)
class Match:
    status: KeywordStatus
    matched_as: str | None
    count: int


def match_term(alternatives: Iterable[str], cv_norm: str, cv_raw: str) -> Match:
    alts = [a for a in alternatives if mnorm(a)]
    for a in alts:
        for v in variants(a):
            if n := count_in(v, cv_norm):
                return Match("exact", v, n)
    for a in alts:
        for al in aliases_of(a):
            if n := count_alias(al, cv_norm, cv_raw):
                return Match("alias_only", al.upper() if _short_upper(al) else al, n)
    return Match("missing", None, 0)


def in_text(term: str, normalized: str, raw: str) -> bool:
    """The term, a variant or an alias appears (used to verify JD terms against the JD)."""
    return match_term([term], normalized, raw).status != "missing"


def lines_of(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


# ------------------------------------------------------------------ sections (R5)

HEADINGS: dict[str, tuple[str, ...]] = {
    "experience": (
        "experience", "work experience", "professional experience", "employment",
        "employment history", "work history", "career history", "relevant experience",
        "internships", "internship experience",
    ),
    "education": ("education", "academic background", "academic qualifications", "qualifications",
                  "education and training", "education & training"),
    "skills": ("skills", "technical skills", "core skills", "key skills", "core competencies",
               "competencies", "skills & tools", "skills and tools", "technologies", "tech stack"),
    "projects": ("projects", "personal projects", "academic projects", "key projects",
                 "selected projects", "project experience"),
    "certifications": ("certifications", "certificates", "licenses", "licenses & certifications",
                       "licenses and certifications", "courses", "certifications & courses"),
    "summary": ("summary", "professional summary", "profile", "professional profile", "about",
                "about me", "objective", "career objective", "personal statement"),
}  # fmt: skip
_HEADING = {h: sec for sec, names in HEADINGS.items() for h in names}


def _heading_key(line: str) -> str:
    # Latin letters, spaces and "&" only: "SKILLS:" -> "skills", "ﺧﻼﺻہ (Summary)" -> "summary".
    return re.sub(r"\s+", " ", re.sub(r"[^a-z& ]+", " ", line.casefold())).strip()


def is_heading_candidate(line: str) -> bool:
    """<= 4 words, <= 40 chars, no final period, ALL CAPS or Title Case (brief R5)."""
    words = line.split()
    if not words or len(words) > 4 or len(line) > 40 or line.endswith("."):
        return False
    if EMAIL_RE.search(line) or re.search(r"\d", line):
        return False
    letters = [c for c in line if c.isalpha() and c.isascii()]
    if len(letters) < 3:
        return _heading_key(line) in _HEADING
    caps = all(c.isupper() for c in letters)
    title = all(
        w[0].isupper() for w in words if w[0].isalpha() and w.casefold() not in ("and", "of", "&")
    )
    return caps or title


@dataclass(frozen=True)
class Layout:
    """Which section each non-empty line belongs to ('top' = before the first heading)."""

    lines: list[str]
    section_of: list[str]
    found: dict[str, str]  # section -> heading as written
    unusual: list[str]  # ALL-CAPS heading-like lines that match no standard heading


def read_layout(text: str) -> Layout:
    lines = lines_of(text)
    current = "top"
    section_of: list[str] = []
    found: dict[str, str] = {}
    unusual: list[str] = []
    for i, line in enumerate(lines):
        sec = _HEADING.get(_heading_key(line)) if len(line.split()) <= 5 else None
        if sec:
            current = sec
            found.setdefault(sec, line)
        elif i > 0 and is_heading_candidate(line) and line.upper() == line:
            unusual.append(line)
        section_of.append(current)
    return Layout(lines, section_of, found, unusual)


def term_sections(term_alts: list[str], layout: Layout) -> list[str]:
    forms = [f for a in term_alts for f in variants(a)]
    hits = {
        sec
        for line, sec in zip(layout.lines, layout.section_of, strict=True)
        if any(count_in(f, mnorm(line)) for f in forms)
    }
    order = ("top", "summary", "experience", "projects", "skills", "education", "certifications")
    return [s for s in order if s in hits]


# ------------------------------------------------------------------ dates (R6)

_MONTHS = r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_MONTH_FULL = (
    r"january|february|march|april|may|june|july|august|september|october|november|december"
)
DATE_FORMATS: dict[str, re.Pattern[str]] = {
    "Month YYYY": re.compile(rf"(?i)\b(?:{_MONTH_FULL})\s+(?:19|20)\d{{2}}\b"),
    "Mon YYYY": re.compile(rf"(?i)\b(?:{_MONTHS})\.?\s+(?:19|20)\d{{2}}\b"),
    "MM/YYYY": re.compile(r"\b(?:0?[1-9]|1[0-2])[/.](?:19|20)\d{2}\b"),
    "YYYY": re.compile(r"(?<![/.\d])(?:19|20)\d{2}(?![/.\d])"),
}
_PRESENT = re.compile(r"(?i)\b(?:present|current|now|today|ongoing)\b")


def date_formats(s: str) -> set[str]:
    found: set[str] = set()
    rest = s
    for name, rx in DATE_FORMATS.items():  # most specific first; consume what matched
        if rx.search(rest):
            found.add(name)
            rest = rx.sub(" ", rest)
    return found


def parses(duration: str) -> bool:
    return bool(date_formats(duration)) or bool(
        _PRESENT.search(duration) and re.search(r"\d{4}", duration)
    )


# ------------------------------------------------------------------ bullets (C1-C6)

ACTION_VERBS = frozenset(
    """accelerated achieved administered advised analysed analyzed architected assembled assessed
    audited automated balanced boosted built calculated championed clarified coached collaborated
    compiled completed composed conceived conducted configured consolidated constructed consulted
    contributed converted coordinated created curated cut debugged decreased defined delivered
    deployed designed detected developed devised diagnosed directed documented doubled drafted drove
    earned edited educated eliminated enabled engineered enhanced established evaluated examined
    executed expanded expedited experimented explored extracted facilitated fine-tuned finetuned
    fixed forecasted formulated founded generated grew guided halved handled headed identified
    implemented improved increased influenced initiated innovated inspected installed instituted
    integrated interviewed introduced invented investigated launched led leveraged lowered maintained
    managed mapped maximized measured mentored merged migrated minimized modeled modelled monitored
    motivated negotiated operated optimised optimized orchestrated organised organized originated
    overhauled oversaw owned partnered performed piloted pioneered planned predicted prepared
    presented prioritized processed produced programmed promoted proposed prototyped proved provided
    published quantified raised ran ranked rebuilt recommended reconciled recruited redesigned reduced
    refactored refined reorganized replaced reported researched resolved restructured revamped
    reviewed revised scaled scheduled scoped scripted secured segmented served set shipped
    simplified simulated slashed solved sourced spearheaded standardized started streamlined
    strengthened structured supervised surveyed synthesized taught tested tracked trained
    transformed translated tripled troubleshot tuned unified upgraded validated visualized won
    wrote""".split()
)
WEAK_OPENERS = (
    "responsible for", "duties included", "duties include", "helped", "assisted", "worked on",
    "involved in", "tasked with", "participated in", "in charge of",
)  # fmt: skip
BUZZWORDS = (
    "hard-working", "hardworking", "hard working", "team player", "detail-oriented",
    "detail oriented", "results-driven", "results driven", "go-getter", "synergy", "passionate",
    "self-starter", "self starter", "dynamic", "motivated individual", "think outside the box",
    "proven track record", "go-to person", "highly motivated", "dedicated professional",
)  # fmt: skip
_BULLET = re.compile(r"^\s*(?:[-*•●▪◦·–]|\d+[.)])\s+")
_QUANT = re.compile(
    r"\d|%|[$£€₨]|\b\d*x\b|\b(?:hours?|days?|weeks?|users?|customers?|clients?|people)\b", re.I
)
_PRONOUN = re.compile(r"(?i)\b(?:i|me|my|myself|we)\b")
_HAS_RANGE = re.compile(r"(?:19|20)\d{2}\s*(?:-|–|to)\s*(?:(?:19|20)\d{2}|present|current)", re.I)


def bullets_from(layout: Layout) -> list[str]:
    """Marked bullets (- • ▪ ...); if the CV has fewer than 3, sentence-like lines under the
    Experience / Projects headings instead (role and title lines with dates are skipped)."""
    marked = [
        b for b in (_BULLET.sub("", ln).strip() for ln in layout.lines if _BULLET.match(ln)) if b
    ]
    if len(marked) >= 3:
        return marked
    out: list[str] = []
    for line, sec in zip(layout.lines, layout.section_of, strict=True):
        if _BULLET.match(line):
            out.append(_BULLET.sub("", line).strip())
        elif (
            sec in ("experience", "projects")
            and len(line.split()) >= 6
            and not _HAS_RANGE.search(line)
            and not date_formats(line)
            and not line.endswith(":")
            and _HEADING.get(_heading_key(line)) is None
        ):
            out.append(line)
    return [b for b in out if b]


def opener(line: str) -> str:
    m = re.match(r"[A-Za-z][A-Za-z-]*", line.strip())
    return m.group(0).casefold() if m else ""


# ------------------------------------------------------------------ check helper


def _check(
    id: str,
    cat: AtsCategoryId,
    title: str,
    status: CheckStatus,
    message: str,
    fix: str | None,
    weight: float,
    *,
    evidence: str | None = None,
    points: float | None = None,
) -> AtsCheck:
    return AtsCheck(
        id=id,
        category=cat,
        title=title,
        status=status,
        weight=0.0 if status == "info" else weight,
        points=round(_POINTS[status] if points is None else points, 3),
        message=message,
        fix=None if status in ("pass", "info") else fix,
        evidence=evidence,
    )


def _band3(value: float, good: float, ok: float) -> CheckStatus:
    return "pass" if value >= good else ("warn" if value >= ok else "fail")


def _quote(s: str, n: int = 90) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# ------------------------------------------------------------------ R: readability (40%)


def r1_text_layer(s: FileSignals) -> AtsCheck:
    pages = list(zip(s.page_chars, s.page_images or [0] * len(s.page_chars), strict=False))
    image_only = [i + 1 for i, (chars, imgs) in enumerate(pages) if chars < 80 and imgs >= 1]
    title = "Text layer (not a scan)"
    fix = (
        "Export the CV again from Word or Google Docs as a PDF ('Save as PDF', not 'Print to "
        "image' or a scan)."
    )
    if image_only and len(image_only) == len(pages):
        return _check("R1", "readability", title, "fail",
                      "Every page looks like an image, so an ATS can't read its text.", fix, 15)  # fmt: skip
    if image_only:
        which = ", ".join(map(str, image_only))
        return _check("R1", "readability", title, "warn",
                      f"Page {which} looks like an image, so its text can't be read by an ATS.", fix, 15)  # fmt: skip
    return _check("R1", "readability", title, "pass", "Every page has selectable text.", None, 15)


_PRIVATE_USE = re.compile("[\ue000-\uf8ff]")
_CID = re.compile(r"\(cid:\d+\)")
_SPACED = re.compile(r"(?<![A-Za-z])(?:[A-Za-z] ){3,}[A-Za-z](?![A-Za-z])")


def r2_clean_chars(text: str) -> AtsCheck:
    bad_chars = (
        text.count("\ufffd")
        + len(_PRIVATE_USE.findall(text))
        + sum(len(m) for m in _CID.findall(text))
    )
    ratio = bad_chars / max(1, len(text))
    spaced = _SPACED.findall(text)
    sample = next((m for m in (_PRIVATE_USE.search(text), _CID.search(text)) if m), None)
    title = "Clean characters"
    fix_chars = (
        "Replace icons with words ('Email:', 'Phone:') and use a standard font such as Calibri, "
        "Arial or Garamond."
    )
    fix_spaced = (
        f"'{spaced[0].strip() if spaced else ''}' is read as separate letters. Type headings "
        "normally and use letter-spacing in styles only."
    )
    if ratio > 0.02:
        return _check("R2", "readability", title, "fail",
                      f"{ratio:.1%} of the characters came out as symbols, which usually means icons or a decorative font.",
                      fix_chars, 15, evidence=sample.group(0) if sample else None)  # fmt: skip
    if ratio >= 0.005 or spaced:
        msg = (
            f"Some characters came out as symbols ({bad_chars} found)."
            if ratio >= 0.005
            else f"{len(spaced)} word(s) are spelled with spaces between the letters."
        )
        return _check("R2", "readability", title, "warn", msg,
                      fix_chars if ratio >= 0.005 else fix_spaced, 15,
                      evidence=spaced[0].strip() if spaced else None)  # fmt: skip
    return _check("R2", "readability", title, "pass",
                  "No garbled symbols, icon glyphs or letter-spaced words.", None, 15)  # fmt: skip


def r3_layout(s: FileSignals) -> AtsCheck:
    title = "Reading order (columns, tables, text boxes)"
    if s.textbox_chars:
        words = (
            sum(len(t.split()) for t in s.lost_samples) if s.lost_samples else s.textbox_chars // 6
        )
        return _check(
            "R3", "readability", title, "fail",
            f"{s.textbox_count} text box(es) hold about {max(words, s.textbox_chars // 6)} words. Many ATS "
            "parsers skip text boxes (HireReady recovered the text for this analysis).",
            "Move the text out of the text boxes into normal paragraphs.", 15,
            evidence=s.lost_samples[-1] if s.lost_samples else None,
        )  # fmt: skip
    share = s.table_chars / s.body_chars if s.body_chars else 0.0
    if s.multi_column_pages or s.docx_columns > 1:
        return _check(
            "R3", "readability", title, "warn",
            "Your CV uses two columns. Modern parsers often read these fine, but some read across "
            "the columns and mix up sections.",
            "For the safest result, use one column. If you keep two, put Experience in the main "
            "column.", 15,
        )  # fmt: skip
    if share > 0.3:
        return _check(
            "R3", "readability", title, "warn",
            f"{share:.0%} of your text sits in tables, which some parsers scramble.",
            "Replace layout tables with plain lines, e.g. 'Role, Company, Jan 2024 - Present'.", 15,
        )  # fmt: skip
    detail = "Text reads top to bottom in one column" + (
        "; no text boxes or layout tables." if s.kind == "docx" else "."
    )
    return _check("R3", "readability", title, "pass", detail, None, 15)


def r4_contact(text: str, cv: CVProfile, s: FileSignals) -> AtsCheck:
    title = "Contact details in the page body"
    email = EMAIL_RE.search(text)
    phone = next(
        (m.group(0) for m in PHONE_RE.finditer(text) if 9 <= len(re.sub(r"\D", "", m.group(0))) <= 15
         and not re.fullmatch(r"\s*(?:19|20)\d{2}\s*-\s*(?:19|20)\d{2}\s*", m.group(0))),
        None,
    )  # fmt: skip
    fix = "Put your name, email, phone and city as the first lines of the page body."
    if s.contact_outside_body:
        where = (
            "page header or footer" if s.contact_outside_body == "header_footer" else "a text box"
        )
        return _check(
            "R4", "readability", title, "fail",
            f"Your email or phone is only in {where}. Greenhouse's own guidance says contact "
            "details in headers, footers or text boxes can be missed.",
            fix, 15, evidence=email.group(0) if email else phone,
        )  # fmt: skip
    if not email:
        return _check("R4", "readability", title, "fail",
                      "No email address in the text an ATS reads.", fix, 15)  # fmt: skip
    name_top = not cv.name or normalize(cv.name) in normalize(text[:300])
    if not phone or not name_top:
        msg = "No phone number found." if not phone else "Your name isn't in the first lines."
        return _check("R4", "readability", title, "warn", msg,
                      "Add a phone number with the country code under your name." if not phone else fix,
                      15, evidence=email.group(0))  # fmt: skip
    return _check("R4", "readability", title, "pass", "Email and phone are in the page body.",
                  None, 15, evidence=email.group(0))  # fmt: skip


def r5_headings(layout: Layout, seniority: Seniority) -> AtsCheck:
    title = "Standard section headings"
    projects_ok = seniority in ("intern", "junior", "unknown")
    missing = []
    if "experience" not in layout.found and not (projects_ok and "projects" in layout.found):
        missing.append("Experience")
    for key, label in (("education", "Education"), ("skills", "Skills")):
        if key not in layout.found:
            missing.append(label)
    found = ", ".join(f"'{h}'" for h in layout.found.values())
    if not missing:
        return _check("R5", "readability", title, "pass", f"Found {found}.", None, 15)
    hint = (
        f" Your heading '{layout.unusual[0]}' may not map to an ATS field."
        if layout.unusual
        else ""
    )
    names = " and ".join(f"'{m}'" for m in missing)
    return _check(
        "R5", "readability", title, "warn" if len(missing) == 1 else "fail",
        f"We couldn't find a standard {names} heading.{hint}",
        f"Use the plain heading{'s' if len(missing) > 1 else ''} {names}. Creative headings make it "
        "harder for parsers to sort your sections.",
        15, evidence=layout.unusual[0] if layout.unusual else None,
    )  # fmt: skip


def r6_dates(text: str, cv: CVProfile) -> AtsCheck:
    title = "Dates an ATS can read"
    entries = [e.duration for e in cv.experience if e.duration] + [
        e.year for e in cv.education if e.year
    ]
    if not entries:
        return _check(
            "R6", "readability", title, "info", "No dated roles or degrees to check.", None, 10
        )
    norm_text = normalize(text)
    good = [d for d in entries if normalize(d) in norm_text and parses(d)]
    bad = [d for d in entries if d not in good]
    formats: set[str] = set()
    for d in good:
        formats |= date_formats(d)
    share = len(good) / len(entries)
    status: CheckStatus = (
        "fail" if share < 0.6 else ("warn" if share < 0.9 or len(formats) >= 3 else "pass")
    )
    msg = f"{len(good)} of {len(entries)} dates are in a format an ATS can read"
    msg += f" ({', '.join(sorted(formats))})." if formats else "."
    if bad:
        msg += f" Couldn't read: '{_quote(bad[0], 40)}'."
    elif len(formats) >= 3:
        msg += " That's 3 different formats."
    return _check("R6", "readability", title, status, msg,
                  "Use one format everywhere, e.g. 'Jun 2024 - Aug 2024'.", 10,
                  evidence=bad[0] if bad else None)  # fmt: skip


def r7_length(text: str, s: FileSignals, seniority: Seniority) -> AtsCheck:
    words = len(text.split())
    pages = s.pages if s.kind == "pdf" and s.pages else max(1, round(words / 500))
    junior = seniority in ("intern", "junior", "unknown")
    max_pages, lo, hi = (1, 300, 800) if junior else (2, 400, 1400)
    level = "an entry-level" if junior else "a mid / senior"
    msg = f"{words} words, {pages} page{'s' if pages != 1 else ''} (target for {level} role: "
    msg += f"{max_pages} page{'s' if max_pages > 1 else ''}, {lo}-{hi} words)."
    fix = "Cut older or unrelated items; keep the bullets that match this job."
    if words < 200 or (junior and pages > 2):
        fix = (
            fix
            if words >= 200
            else "Add detail to your projects and experience: aim for 300-800 words."
        )
        return _check("R7", "readability", "Length", "fail", msg, fix, 10)
    if pages <= max_pages and lo <= words <= hi:
        return _check("R7", "readability", "Length", "pass", msg, None, 10)
    if words < lo:
        fix = "Add one or two more results-focused bullets to your strongest roles or projects."
    return _check("R7", "readability", "Length", "warn", msg, fix, 10)


def _shingles(text: str, n: int = 8) -> set[str]:
    words = re.findall(r"[a-z0-9+#]+", normalize(text))
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def r8_hidden(text: str, jd_text: str, s: FileSignals) -> AtsCheck:
    title = "No hidden or pasted text"
    jd = _shingles(jd_text)
    pasted = len(jd & _shingles(text)) / len(jd) if jd else 0.0
    fix = "Remove it. Hidden text often shows up in plain view after parsing."
    if looks_like_injection(text) or pasted > 0.15:
        why = (
            "text that reads like instructions to an AI ('ignore previous…')"
            if looks_like_injection(text)
            else f"{pasted:.0%} of the job post copied word for word"
        )
        return _check("R8", "readability", title, "fail",
                      f"Your CV contains {why}. Recruiter AI tools flag this as manipulation.", fix, 5)  # fmt: skip
    if s.light_text_chars > 30:
        return _check("R8", "readability", title, "warn",
                      f"{s.light_text_chars} characters of white or near-white text. On a dark sidebar that "
                      "is fine; hidden keywords are not: the parsed text shows them to the recruiter.",
                      "Remove any invisible text; a plain one-column layout avoids the question.", 5)  # fmt: skip
    return _check("R8", "readability", title, "pass", "No hidden or copied text found.", None, 5)


def info_checks(text: str, s: FileSignals) -> list[AtsCheck]:
    out = []
    if s.kind == "text":
        out.append(_check("I1", "readability", "File type", "info",
                          "Sample CV supplied as text. For your own CV, PDF and DOCX both work; "
                          "Greenhouse recommends PDF.", None, 0))  # fmt: skip
    else:
        out.append(_check("I1", "readability", "File type", "info",
                          f"{s.kind.upper()}: PDF and DOCX both work; Greenhouse recommends PDF.", None, 0))  # fmt: skip
    if s.image_count:
        out.append(_check("I2", "readability", "Images", "info",
                          f"{s.image_count} image(s) or icon(s). ATSs ignore images, so anything shown "
                          "only as a picture (skill bars, logos, icons) is lost. Whether to include a "
                          "photo depends on the country.", None, 0))  # fmt: skip
    if s.generic_file_name:
        out.append(_check("I3", "readability", "File name", "info",
                          "Your file name is generic. 'Firstname_Lastname_CV.pdf' reads better to a "
                          "recruiter than 'final_v3.pdf'.", None, 0))  # fmt: skip
    if not re.search(r"(?i)linkedin\.com/in/", text):
        out.append(_check("I4", "readability", "LinkedIn", "info",
                          "Add your LinkedIn URL (linkedin.com/in/...) next to your email.", None, 0))  # fmt: skip
    return out


# ------------------------------------------------------------------ K: keywords (45%)

_GENERIC = re.compile(
    r"(?i)\b(?:fundamentals|basics|basic|concepts|principles|knowledge(?: of)?|experience(?: with| in)?|"
    r"skills?|proficiency(?: in)?|familiarity(?: with)?|understanding(?: of)?|strong|solid|good|"
    r"working|hands[ -]on|programming|ideally|advanced|deep|excellent)\b"
)
_SPLIT_ALT = re.compile(r"\s+or\s+|\s*/\s*")
_SLASH_TERMS = re.compile(r"(?i)\b(?:ci/cd|ui/ux|ux/ui|a/b|tcp/ip|i/o|b2b/b2c|r&d)\b")
_SPLIT_AND = re.compile(r"\s*,\s*|\s+and\s+|\s*&\s*|\s+with\s+|\s*\(\s*|\s*\)\s*")
_WRAPPERS = ("pipelines", "pipeline", "systems", "applications", "apps", "frameworks", "framework",
             "tools", "development", "methods")  # fmt: skip


def skill_parts(name: str) -> list[list[str]]:
    """JD skill name -> parts (each its own keyword) -> alternatives (any counts).
    'LLMs and RAG pipelines' -> [['LLMs'], ['RAG pipelines', 'RAG']]; 'AWS or GCP' -> [['AWS', 'GCP']].
    """
    parts: list[list[str]] = []
    for part in _SPLIT_AND.split(name):
        alts: list[str] = []
        pieces = _SPLIT_ALT.split(part)
        # "CI/CD", "UI/UX", "A/B testing" are one term, not alternatives ("AWS/GCP" is).
        if _SLASH_TERMS.search(part):
            pieces = re.split(r"\s+or\s+", part)
        for a in (x.strip(" .-") for x in pieces):
            if not a:
                continue
            core = re.sub(r"\s+", " ", _GENERIC.sub(" ", a)).strip(" .-")
            if core:
                alts.append(core)
                words = core.split()
                if len(words) == 2 and words[1].casefold() in _WRAPPERS:
                    alts.append(words[0])
        if alts:
            parts.append(list(dict.fromkeys(alts)))
    return parts


_SENIORITY = re.compile(
    r"(?i)\b(?:junior|jr|senior|sr|mid(?:[- ]level)?|lead|principal|staff|intern|trainee|graduate|"
    r"entry(?:[- ]level)?|associate|head of|i{1,3}|iv)\b\.?"
)
_STOP = frozenset("a an and the of for to in at with".split())


def core_title(title: str) -> str:
    t = re.split(r"\s+[-–—|@,(]\s*|\s+at\s+", title.strip(), maxsplit=1)[0]
    return re.sub(r"\s+", " ", _SENIORITY.sub(" ", t)).strip(" -")


_DEGREE_LEVELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Associate degree", re.compile(r"(?i)\bassociate'?s? degree\b")),
    ("Bachelor's degree", re.compile(
        r"(?i:\bbachelor'?s?\b|\bundergraduate degree\b)|\b(?:BS|BSc|B\.S\.?|BA|B\.A\.?|BE|B\.E\.?|BEng|BBA|BCS|B\.?Tech)\b")),
    ("Master's degree", re.compile(
        r"(?i:\bmaster'?s?\b(?! of ceremonies))|\b(?:MSc|M\.S\.?|MA|M\.A\.?|MBA|MEng|M\.?Tech|MPhil)\b|\bMS\b(?!\s+(?:Office|Excel|Word|Teams|Access|Project))")),
    ("PhD", re.compile(r"(?i)\bph\.?\s?d\b|\bdoctorate\b|\bdoctoral\b")),
)  # fmt: skip


def degree_level(text: str) -> int | None:
    best = None
    for i, (_, rx) in enumerate(_DEGREE_LEVELS):
        if rx.search(text):
            best = i
    return best


def _where(term: str, importance: KeywordImportance, m: Match, quote: str | None) -> str | None:
    if m.status == "exact":
        return None
    if m.status == "alias_only":
        return (
            f"You wrote '{m.matched_as}'; also write '{term}' once, e.g. '{term} ({m.matched_as})'."
        )
    if quote:
        return f"Add the exact words '{term}' to the bullet that proves it: \"{_quote(quote)}\""
    if importance == "title":
        return f"If it's accurate, add a headline under your name, e.g. '{term} · ' + your top 2-3 skills."
    if importance == "credential":
        return f"If you have it, write '{term}' exactly as named under Education or Certifications."
    return f"Only if it's true: add '{term}' to your Skills section and to the bullet where you used it."


@dataclass(frozen=True)
class Inputs:
    cv_raw: str
    cv_norm: str
    jd_raw: str
    jd_norm: str
    layout: Layout


def _hit(
    inp: Inputs, term: str, alts: list[str], importance: KeywordImportance, gap: GapItem | None
) -> KeywordHit:
    m = match_term(alts, inp.cv_norm, inp.cv_raw)
    proven = bool(
        m.status == "missing" and gap and gap.verdict != "no_evidence" and gap.quote_verified
        and gap.evidence_quote
    )  # fmt: skip
    quote = gap.evidence_quote if proven and gap else None
    jd_count = max((count_in(v, inp.jd_norm) for a in alts for v in variants(a)), default=0) or max(
        (count_alias(al, inp.jd_norm, inp.jd_raw) for a in alts for al in aliases_of(a)), default=0
    )
    return KeywordHit(
        term=term,
        importance=importance,
        status=m.status,
        matched_as=m.matched_as if m.status == "alias_only" else None,
        count=m.count,
        jd_count=max(1, jd_count),
        sections=term_sections([m.matched_as] if m.matched_as else alts, inp.layout)
        if m.count
        else [],
        proven_not_searchable=proven,
        evidence_quote=quote,
        where_to_add=_where(term, importance, m, quote),
    )


def _jd_wording(alts: list[str], inp: Inputs) -> str | None:
    """The JD's own spelling of the term, or None if the JD doesn't contain it at all."""
    for a in alts:
        for v in variants(a):
            if count_in(v, inp.jd_norm):
                return a
    for a in alts:
        for al in aliases_of(a):
            if count_alias(al, inp.jd_norm, inp.jd_raw):
                return a
    return None


def keyword_hits(inp: Inputs, job: JobProfile, gaps: list[GapItem]) -> list[KeywordHit]:
    gap_by = {g.skill.casefold(): g for g in gaps}
    hits: list[KeywordHit] = []
    seen: set[str] = set()
    groups: tuple[tuple[KeywordImportance, list[str]], ...] = (
        ("must_have", [s.name for s in job.must_have_skills]),
        ("nice_to_have", [s.name for s in job.nice_to_have_skills]),
    )
    for importance, names in groups:
        for name in names:
            for alts in skill_parts(name):
                term = _jd_wording(alts, inp)  # never ask for a word the JD doesn't contain
                if term is None or mnorm(term) in seen:
                    continue
                seen.add(mnorm(term))
                hits.append(_hit(inp, term, alts, importance, gap_by.get(name.casefold())))
    core = core_title(job.title)
    if core and in_text(core, inp.jd_norm, inp.jd_raw):
        hits.append(_hit(inp, core, [core], "title", None))
    for degree in job.required_degrees:
        if in_text(degree, inp.jd_norm, inp.jd_raw) and mnorm(degree) not in seen:
            seen.add(mnorm(degree))
            hits.append(_degree_hit(inp, degree))
    for cert in job.required_certifications:
        if in_text(cert, inp.jd_norm, inp.jd_raw) and mnorm(cert) not in seen:
            seen.add(mnorm(cert))
            hits.append(_hit(inp, cert, [cert], "credential", None))
    return hits


def _degree_hit(inp: Inputs, degree: str) -> KeywordHit:
    need, have = degree_level(degree), degree_level(inp.cv_raw)
    if need is None:  # "a degree in Computer Science": any degree counts, plus the field
        need = 1
    if have is not None and have >= need:
        m = Match("exact", _DEGREE_LEVELS[have][0], 1)
    elif have is not None:
        m = Match("alias_only", _DEGREE_LEVELS[have][0], 1)  # a degree, at another level
    else:
        m = Match("missing", None, 0)
    hit = _hit(inp, degree, [degree], "credential", None)
    return hit.model_copy(
        update={
            "status": m.status,
            "matched_as": m.matched_as if m.status != "exact" else None,
            "count": m.count,
            "sections": ["education"] if m.count else [],
            "where_to_add": None
            if m.status == "exact"
            else (
                f"The job asks for '{degree}'; your CV shows a {m.matched_as}. Apply anyway if the "
                "rest fits, and expect a screening question about it."
                if m.status == "alias_only"
                else _where(degree, "credential", m, None)
            ),
        }
    )


def _coverage_check(
    id: str, title: str, hits: list[KeywordHit], weight: float, label: str
) -> AtsCheck | None:
    if not hits:
        return None
    share = sum(TERM_POINTS[h.status] for h in hits) / len(hits)
    exact = sum(1 for h in hits if h.status == "exact")
    alias = sum(1 for h in hits if h.status == "alias_only")
    missing = [h.term for h in hits if h.status == "missing"]
    msg = f"{exact} of {len(hits)} {label} keywords found as written"
    msg += f", {alias} only in another form." if alias else "."
    if missing:
        msg += f" Missing: {', '.join(missing[:6])}{'…' if len(missing) > 6 else ''}."
    return _check(
        id, "keywords", title, _band3(share, 0.8, 0.5), msg,
        "Add the missing terms you really have, in the job's exact words (see the keyword chips).",
        weight, points=share,
    )  # fmt: skip


def keyword_checks(hits: list[KeywordHit], inp: Inputs) -> list[AtsCheck]:
    out: list[AtsCheck] = []
    for check in (
        _coverage_check("K1", "Must-have keywords", [h for h in hits if h.importance == "must_have"], 55, "must-have"),
        _coverage_check("K2", "Nice-to-have keywords", [h for h in hits if h.importance == "nice_to_have"], 15, "nice-to-have"),
    ):  # fmt: skip
        if check:
            out.append(check)
    title = next((h for h in hits if h.importance == "title"), None)
    if title:
        tokens = [t for t in mnorm(title.term).split() if t not in _STOP]
        found = [t for t in tokens if any(count_in(v, inp.cv_norm) for v in variants(t))]
        status: CheckStatus = (
            "pass" if title.status == "exact"
            else ("warn" if tokens and len(found) / len(tokens) >= 0.5 else "fail")
        )  # fmt: skip
        msg = (
            f"'{title.term}' appears in your CV."
            if status == "pass"
            else f"Recruiters often search by job title. '{title.term}' doesn't appear in your CV"
            + (f" (only {', '.join(found)})." if found else ".")
        )
        out.append(_check("K3", "keywords", "Job title", status, msg, title.where_to_add, 15))
    creds = [h for h in hits if h.importance == "credential"]
    if creds:
        worst = min(creds, key=lambda h: TERM_POINTS[h.status])
        status = {"exact": "pass", "alias_only": "warn", "missing": "fail"}[worst.status]  # type: ignore[assignment]
        msg = "; ".join(
            f"'{h.term}': " + {"exact": "found", "alias_only": f"you have {h.matched_as}", "missing": "not found"}[h.status]
            for h in creds
        )  # fmt: skip
        out.append(_check("K4", "keywords", "Required degree & certifications", status, msg + ".",
                          worst.where_to_add, 10))  # fmt: skip
    out.append(k5_stuffing(hits, inp))
    return out


def k5_stuffing(hits: list[KeywordHit], inp: Inputs) -> AtsCheck:
    over = sorted((h for h in hits if h.count > 6), key=lambda h: -h.count)
    long_line = next((ln for ln in inp.layout.lines if ln.count(",") >= 25), None)
    if over:
        h = over[0]
        return _check("K5", "keywords", "No keyword stuffing", "warn",
                      f"'{h.term}' appears {h.count} times. Repetition doesn't help with recruiters and reads as stuffing.",
                      "Mention it where you used it; 2-3 times is plenty.", 5)  # fmt: skip
    if long_line:
        n = long_line.count(",") + 1
        return _check("K5", "keywords", "No keyword stuffing", "warn",
                      f"One skills line lists {n} items.", "Keep the 10-15 skills that matter for this job.", 5,
                      evidence=_quote(long_line))  # fmt: skip
    return _check("K5", "keywords", "No keyword stuffing", "pass",
                  "No keyword is repeated more than 6 times.", None, 5)  # fmt: skip


def knockouts(job: JobProfile, inp: Inputs) -> list[str]:
    """Hard requirements stated in the JD (each verified in the JD text)."""
    out: list[str] = []
    if job.work_authorization and normalize(job.work_authorization) in normalize(inp.jd_raw):
        out.append(f"Work authorisation: {job.work_authorization}")
    if job.min_years and re.search(
        rf"\b{job.min_years}\s*\+?\s*(?:-\s*\d+\s*)?(?:years?|yrs?)\b", inp.jd_raw, re.I
    ):
        out.append(
            f"At least {job.min_years} year{'s' if job.min_years != 1 else ''} of experience"
        )
    out += [f"Degree: {d}" for d in job.required_degrees if in_text(d, inp.jd_norm, inp.jd_raw)]
    out += [
        f"Certification: {c}"
        for c in job.required_certifications
        if in_text(c, inp.jd_norm, inp.jd_raw)
    ]
    return out[:6]


# ------------------------------------------------------------------ C: content quality (15%)


def content_checks(layout: Layout, text: str) -> list[AtsCheck]:
    bullets = bullets_from(layout)
    if not bullets:
        return [_check("C1", "content", "Bullet points", "fail",
                       "No bullet points found under Experience or Projects.",
                       "Describe each role and project in 2-4 bullets that start with a verb.", 30)]  # fmt: skip
    n = len(bullets)
    quant = [b for b in bullets if _QUANT.search(b)]
    weak = [b for b in bullets if any(b.casefold().startswith(w) for w in WEAK_OPENERS)]
    strong = [b for b in bullets if opener(b) in ACTION_VERBS and b not in weak]
    lengths = [len(b.split()) for b in bullets]
    in_range = sum(1 for w in lengths if 8 <= w <= 35)
    long_ones = [b for b, w in zip(bullets, lengths, strict=True) if w > 35]
    short_ones = [b for b, w in zip(bullets, lengths, strict=True) if w < 8]
    pronouns = sum(len(_PRONOUN.findall(b)) for b in bullets)
    pron_line = next((b for b in bullets if _PRONOUN.search(b)), None)
    lowered = normalize(text)
    buzz = [w for w in BUZZWORDS if w in lowered]
    openers = Counter(opener(b) for b in bullets if opener(b))
    repeated = [w for w, c in openers.most_common() if c > 3]
    q, s_ = len(quant) / n, len(strong) / n
    length_share = in_range / n
    no_num = next((b for b in bullets if not _QUANT.search(b)), None)
    return [
        _check("C1", "content", "Quantified results", _band3(q, 0.4, 0.2),
               f"{len(quant)} of {n} bullets show a measurable result.",
               "Add the number you actually know: users, time saved, accuracy, size of the dataset.",
               30, evidence=_quote(no_num) if no_num and q < 0.4 else None),
        _check("C2", "content", "Strong openers", _band3(s_, 0.7, 0.4),
               f"{len(strong)} of {n} bullets start with an action verb"
               + (f"; {len(weak)} start weakly." if weak else "."),
               "Start with what you did: 'Built…', 'Automated…', 'Reduced…'.", 25,
               evidence=_quote(weak[0]) if weak else None),
        _check("C3", "content", "Bullet length", _band3(length_share, 0.8, 0.6),
               f"{in_range} of {n} bullets are 8-35 words"
               + (f"; {len(long_ones)} longer." if long_ones else (f"; {len(short_ones)} shorter." if short_ones else ".")),
               "Split long bullets (one result each) and give short ones a result.", 15,
               evidence=_quote((long_ones or short_ones or [""])[0]) or None),
        _check("C4", "content", "No pronouns", "pass" if pronouns == 0 else ("warn" if pronouns <= 2 else "fail"),
               "Bullets are written without 'I' or 'my'." if pronouns == 0 else f"{pronouns} pronoun(s) ('I', 'my', 'we') in your bullets.",
               "Drop the pronoun: 'I built' -> 'Built'.", 10, evidence=_quote(pron_line) if pron_line else None),
        _check("C5", "content", "No buzzwords", "pass" if len(buzz) <= 1 else ("warn" if len(buzz) <= 3 else "fail"),
               "No clichés like 'results-driven team player'." if not buzz else f"Clichés found: {', '.join(repr(b) for b in buzz[:4])}.",
               "Replace them with one proof, e.g. a project result.", 10),
        _check("C6", "content", "Varied openers", "pass" if not repeated else ("warn" if len(repeated) == 1 else "fail"),
               "No opening verb is used more than 3 times." if not repeated
               else f"'{repeated[0].capitalize()}' starts {openers[repeated[0]]} bullets.",
               "Vary them: built, designed, shipped, automated.", 10),
    ]  # fmt: skip


# ------------------------------------------------------------------ total


def _component(checks: list[AtsCheck], weight: float) -> tuple[AtsComponent, bool]:
    scored = [c for c in checks if c.weight > 0]
    if not scored:
        return AtsComponent(weight=weight, score=0.0, detail="No checks apply."), False
    value = sum(c.weight * c.points for c in scored) / sum(c.weight for c in scored)
    passed = sum(1 for c in scored if c.status == "pass")
    return (
        AtsComponent(
            weight=weight,
            score=round(value, 3),
            detail=f"{passed} of {len(scored)} checks passed",
        ),
        True,
    )


def compute_ats(
    cv_text: str,
    jd_text: str,
    signals: FileSignals | None,
    cv: CVProfile,
    job: JobProfile,
    gaps: list[GapItem],
) -> AtsReport:
    s = signals or FileSignals(kind="text")
    layout = read_layout(cv_text)
    inp = Inputs(cv_text, mnorm(cv_text), jd_text, mnorm(jd_text), layout)
    readability = [
        r1_text_layer(s),
        r2_clean_chars(cv_text),
        r3_layout(s),
        r4_contact(cv_text, cv, s),
        r5_headings(layout, job.seniority),
        r6_dates(cv_text, cv),
        r7_length(cv_text, s, job.seniority),
        r8_hidden(cv_text, jd_text, s),
        *info_checks(cv_text, s),
    ]
    hits = keyword_hits(inp, job, gaps)
    keywords = keyword_checks(hits, inp)
    content = content_checks(layout, cv_text)
    parts = {
        "readability": _component(readability, WEIGHTS["readability"]),
        "keywords": _component(keywords, WEIGHTS["keywords"]),
        "content": _component(content, WEIGHTS["content"]),
    }
    used = {k: comp for k, (comp, ok) in parts.items() if ok}
    total_w = sum(c.weight for c in used.values())
    raw = 100 * sum(c.weight * c.score for c in used.values()) / total_w if total_w else 0.0
    gated = any(c.id in GATE_CHECKS and c.status == "fail" for c in readability)
    score = max(0, min(100, round(min(raw, GATE_CAP) if gated else raw)))
    _, band, label = next(b for b in BANDS if score >= b[0])
    order = {"fail": 0, "warn": 1, "pass": 2, "info": 3}
    checks = sorted([*readability, *keywords, *content], key=lambda c: order[c.status])
    return AtsReport(
        score=score,
        band=band,
        band_label=label,
        formula=FORMULA,
        gated=gated,
        readability=parts["readability"][0],
        keywords=parts["keywords"][0],
        content=parts["content"][0],
        checks=checks,
        keyword_hits=hits,
        knockouts=knockouts(job, inp),
        file_kind=s.kind,
    )
