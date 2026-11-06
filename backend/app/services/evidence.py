"""Anti-hallucination guard: an evidence quote only counts if it really exists in the CV.

LLMs sometimes "quote" text that was never there. We normalize both strings (case, whitespace,
curly quotes, dashes, bullet symbols) and require the quote to be a substring of the CV.
If it isn't, the verdict is downgraded to `no_evidence`.
"""

import re
import unicodedata

from app.schemas.analysis import JobSkill, SkillJudgement, Verdict

_TRANSLATE = str.maketrans(
    {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "−": "-",
        "•": " ", "●": " ", "▪": " ", "·": " ",
    }
)  # fmt: skip
_WS = re.compile(r"\s+")
MIN_QUOTE_CHARS = 8


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE).casefold()
    return _WS.sub(" ", text).strip()


def quote_in_text(quote: str | None, normalized_source: str) -> bool:
    if not quote:
        return False
    q = normalize(quote).strip(" .,;:\"'")
    return len(q) >= MIN_QUOTE_CHARS and q in normalized_source


def validate_judgement(
    judgement: SkillJudgement | None, skill: JobSkill, normalized_cv: str
) -> tuple[Verdict, str | None, str, bool]:
    """Return (verdict, quote, reason, quote_verified) after the quote check."""
    if judgement is None:
        return "no_evidence", None, "No evidence found in the CV.", False
    if judgement.verdict == "no_evidence":
        return "no_evidence", None, judgement.reason or "No evidence found in the CV.", False
    if quote_in_text(judgement.evidence_quote, normalized_cv):
        return judgement.verdict, judgement.evidence_quote, judgement.reason, True
    return (
        "no_evidence",
        None,
        "No evidence found: the quoted text could not be located in the CV.",
        False,
    )
