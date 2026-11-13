"""ATS readiness eval: synthetic CV files with a hand-written expected status per check.

Each case is built in code (PDF / DOCX bytes, using the backend's QA fixture builders), parsed by
the real upload path (`extract_cv`), then scored by `compute_ats`. The ATS check is deterministic
(no LLM), so fake and live mode give the same numbers. Labels were written before the first run.

"Flagged" = warn or fail. Flag precision: of the checks we flagged, how many the label also flags;
flag recall: of the labelled problems, how many we flagged. Exact status accuracy is reported too.
"""

import io
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.schemas.analysis import CVProfile, Education, Experience, JobProfile, JobSkill
from app.services.ats import compute_ats
from app.services.parsing import DOCX_MIME, extract_cv
from tests.fixtures.builders import PAGE_H, Item, _content, _image_content, build_pdf, two_column_pdf

CV = """SANA MALIK
Karachi, Pakistan | sana.malik.demo@example.com | +92 321 7654321 | linkedin.com/in/sana-malik-demo

SUMMARY
Junior Data Analyst who turns sales data into dashboards and decisions.

EXPERIENCE
Data Analyst Intern, Indus Retail (fictional), Jun 2025 - Sep 2025
- Built 6 Power BI dashboards used by 40 store managers every week.
- Wrote SQL queries in PostgreSQL that cut monthly reporting time by 70%.
- Automated a weekly Excel report with Python and pandas, saving 5 hours a week.
- Presented a churn analysis to 3 regional leads that led to a new loyalty offer.

PROJECTS
Delivery Time Forecast
- Trained a gradient boosting model on 18,000 orders that predicted delivery time within 9 minutes.

EDUCATION
BS Computer Science, Karachi Institute of Technology (fictional), 2021 - 2025

SKILLS
SQL, Python, pandas, Power BI, Excel, PostgreSQL, Statistics, Git
"""

JD = """Junior Data Analyst - Crescent Foods (fictional), Karachi

Requirements
- Bachelor's degree in Computer Science, Statistics or a related field.
- Strong SQL and Excel skills.
- Experience building dashboards in Power BI or Tableau.
- Python with pandas for data cleaning.
Nice to have
- Experience with A/B testing.
We review every application by hand. Applicants must be based in Karachi.
"""

PROFILE = CVProfile(
    name="Sana Malik",
    education=[Education(degree="BS Computer Science", institution="KIT", year="2021 - 2025")],
    skills=[],
    projects=[],
    experience=[Experience(role="Data Analyst Intern", org="Indus Retail", duration="Jun 2025 - Sep 2025", bullets=[])],
    certifications=[],
)
JOB = JobProfile(
    title="Junior Data Analyst",
    seniority="junior",
    must_have_skills=[JobSkill(name=n, competency="data_handling") for n in ("SQL", "Excel", "Power BI or Tableau", "Python", "pandas")],
    nice_to_have_skills=[JobSkill(name="A/B testing", competency="data_handling")],
    responsibilities=[], tools=[], soft_skills=[],
    required_degrees=["Bachelor's degree in Computer Science"], required_certifications=[],
    min_years=None, work_authorization="based in Karachi",
)  # fmt: skip


def _lines_pdf(text: str, right: dict[int, str] | None = None) -> bytes:
    items = []
    for i, line in enumerate(text.splitlines()):
        y = PAGE_H - 50 - i * 13
        if line:
            items.append(Item(50, y, line))
        if right and i in right:
            items.append(Item(470, y, right[i]))
    return build_pdf([_content(items)])


def _docx(lines: list[str], *, header: str | None = None, textbox: str | None = None) -> bytes:
    import docx

    d = docx.Document()
    for line in lines:
        d.add_paragraph(line)
    if header:
        d.sections[0].header.paragraphs[0].text = header
    buf = io.BytesIO()
    d.save(buf)
    if not textbox:
        return buf.getvalue()
    src, out = zipfile.ZipFile(io.BytesIO(buf.getvalue())), io.BytesIO()
    box = f"<w:txbxContent><w:p><w:r><w:t>{textbox}</w:t></w:r></w:p></w:txbxContent>"
    with zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/document.xml":
                data = (
                    data.decode()
                    .replace("<w:body>", f"<w:body><w:p><w:r><w:pict>{box}{box}</w:pict></w:r></w:p>", 1)
                    .encode()
                )
            dst.writestr(item, data)
    return out.getvalue()


def _two_column() -> bytes:
    lines = CV.splitlines()
    side = "\n".join(lines[:2] + lines[-8:])
    main = "\n".join(lines[3:18])
    return two_column_pdf(side, main)


def _scanned_page() -> bytes:
    page1 = _content([Item(50, PAGE_H - 50 - i * 13, ln) for i, ln in enumerate(CV.splitlines()) if ln])
    return build_pdf([page1, _image_content()])


@dataclass(frozen=True)
class Case:
    id: str
    describe: str
    build: Callable[[], tuple[bytes, str]]
    expect: dict[str, str]  # check id -> expected status (only the checks this case is about)


PDF = "application/pdf"
CASES: list[Case] = [
    Case("clean_pdf", "clean single-column PDF", lambda: (_lines_pdf(CV), PDF),
         {"R1": "pass", "R2": "pass", "R3": "pass", "R4": "pass", "R5": "pass", "R6": "pass", "R8": "pass"}),
    Case("right_dates", "right-aligned dates and city (must NOT count as columns)",
         lambda: (_lines_pdf(CV, {i: "Jun 2025 - Sep 2025" for i in range(6, 12)} | {i: "Karachi" for i in range(14, 17)}), PDF),
         {"R3": "pass"}),
    Case("two_column", "sidebar + main column PDF", lambda: (_two_column(), PDF), {"R3": "warn"}),
    Case("scanned_page", "page 2 is an image", lambda: (_scanned_page(), PDF), {"R1": "warn"}),
    Case("textbox_docx", "DOCX with a text-box sidebar", lambda: (_docx(CV.splitlines(), textbox="Tableau, Looker, BigQuery"), DOCX_MIME),
         {"R3": "fail", "R4": "pass"}),
    Case("header_contact_docx", "DOCX with email and phone only in the page header",
         lambda: (_docx([ln for ln in CV.splitlines() if "@" not in ln], header="sana.malik.demo@example.com | +92 321 7654321"), DOCX_MIME),
         {"R4": "fail", "R3": "pass"}),
    Case("icon_font", "icon-font glyphs for contact and section icons",
         lambda: (_docx([ln.replace("|", "") for ln in CV.splitlines()] + ["" * 40]), DOCX_MIME),
         {"R2": "fail"}),
    Case("letter_spaced", "letter-spaced headings", lambda: (_docx(CV.replace("SKILLS", "S K I L L S").splitlines()), DOCX_MIME),
         {"R2": "warn"}),
    Case("pasted_jd", "the job post pasted into the CV", lambda: (_docx((CV + "\n" + JD).splitlines()), DOCX_MIME),
         {"R8": "fail"}),
    Case("creative_headings", "creative headings instead of standard ones",
         lambda: (_docx(re.sub(r"\b(EXPERIENCE|EDUCATION)\b", lambda m: {"EXPERIENCE": "MY JOURNEY", "EDUCATION": "WHERE I LEARNED"}[m.group(1)], CV).splitlines()), DOCX_MIME),
         {"R5": "fail"}),
    Case("no_email", "no email address anywhere", lambda: (_docx(CV.replace("sana.malik.demo@example.com | ", "").splitlines()), DOCX_MIME),
         {"R4": "fail"}),
]  # fmt: skip


def run_case(case: Case) -> dict[str, Any]:
    data, mime = case.build()
    parsed = extract_cv(data, mime)
    report = compute_ats(parsed.text, JD, parsed.signals, PROFILE, JOB, [])
    got = {c.id: c.status for c in report.checks}
    return {
        "id": case.id,
        "describe": case.describe,
        "score": report.score,
        "expect": case.expect,
        "got": {k: got.get(k, "absent") for k in case.expect},
        "deterministic": compute_ats(parsed.text, JD, parsed.signals, PROFILE, JOB, []) == report,
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, int]:
    flagged = {"warn", "fail"}
    tp = fp = fn = exact = total = 0
    for r in rows:
        for cid, want in r["expect"].items():
            got = r["got"][cid]
            total += 1
            exact += got == want
            tp += got in flagged and want in flagged
            fp += got in flagged and want not in flagged
            fn += got not in flagged and want in flagged
    return {"tp": tp, "fp": fp, "fn": fn, "exact": exact, "total": total}
