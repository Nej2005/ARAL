"""Grading for the three question types (BACKEND.md §10.2)."""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

from app.config import settings

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")
_ARTICLE = re.compile(r"^(the|a|an)\s+")


def normalize_answer(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return _ARTICLE.sub("", s)


def grade(question_type: str, correct_answer: str, accepted_answers: list[str], response: str,
          threshold: int | None = None) -> tuple[bool, str | None]:
    """Returns (is_correct, match_note)."""
    response = (response or "").strip()
    if question_type == "mcq":
        return response == correct_answer, None
    if question_type == "true_false":
        return response.lower() in ("true", "false") and response.lower() == correct_answer, None
    # identification
    threshold = settings.ident_fuzzy_threshold if threshold is None else threshold
    r = normalize_answer(response)
    if not r:
        return False, None
    accepted = [normalize_answer(a) for a in (accepted_answers or [correct_answer]) if a]
    if r in accepted:
        return True, None
    for a in accepted:
        if fuzz.ratio(r, a) >= threshold:
            return True, "typo_tolerated"
    return False, None


def term_matches(response: str, term: str, min_ratio: int = 90) -> bool:
    r, t = normalize_answer(response), normalize_answer(term)
    return bool(r and t) and (r == t or fuzz.ratio(r, t) >= min_ratio)
