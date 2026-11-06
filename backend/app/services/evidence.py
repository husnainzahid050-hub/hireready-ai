"""Anti-hallucination guard: an evidence quote only counts if it really exists in the CV.

LLMs sometimes "quote" text that was never there. We normalize both strings (case, whitespace,
curly quotes, dashes, bullet symbols) and require the quote to be a substring of the CV.
If it isn't, the verdict is downgraded to `no_evidence`.

Security: the candidate controls the CV, so "the quote exists" does not prove the quote is
honest evidence. A quote that reads like an instruction to the model (prompt injection) or is
far longer than the one sentence we asked for is rejected too.
"""

import re
import unicodedata

from app.core.injection import looks_like_injection
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
MAX_QUOTE_CHARS = 400  # the prompt asks for < 200; anything much longer is not "one sentence"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE).casefold()
    return _WS.sub(" ", text).strip()


def quote_in_text(quote: str | None, normalized_source: str) -> bool:
    if not quote or len(quote) > MAX_QUOTE_CHARS or looks_like_injection(quote):
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
    if looks_like_injection(judgement.evidence_quote):
        return (
            "no_evidence",
            None,
            "No evidence found: the quoted text reads like instructions, not experience.",
            False,
        )
    return (
        "no_evidence",
        None,
        "No evidence found: the quoted text could not be located in the CV.",
        False,
    )
