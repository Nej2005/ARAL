"""Every "stay close to the lesson's wording" check lives here (BACKEND.md §6.3, §9).

Nothing in this module calls the LLM. Normalization happens only inside comparisons;
the stored text is always the document's own text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

BLANK = "_____"
QUOTE_CHARS = "\"'“”‘’"

_WS = re.compile(r"\s+")
_CONT = re.compile(
    r"\s*(\((?:cont\.?|cont'd|continued)\)|[-–—:]\s*(?:part|pt\.?)\s*\d+|\b(?:cont\.?|cont'd|continued)\b)\s*$",
    re.IGNORECASE,
)
_LEADING_BULLET = re.compile(r"^\s*(?:[•●▪■–\-\*·]|\d+[.)])\s+")


def normalize_ws(s: str) -> str:
    return _WS.sub(" ", s).strip()


def norm_cmp(s: str) -> str:
    """Comparison form: casefolded, whitespace collapsed, quotes/dashes unified."""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    return normalize_ws(s).casefold()


def strip_bullet(s: str) -> str:
    return _LEADING_BULLET.sub("", s, count=1)


def clean_for_display(s: str) -> str:
    """Allowed light cleanup (§9): trim, drop a leading bullet, join wrapped lines."""
    lines = [strip_bullet(l).strip() for l in s.splitlines()]
    return normalize_ws(" ".join(l for l in lines if l))


def topic_key(topic: str | None) -> str | None:
    if not topic:
        return None
    t = normalize_ws(topic)
    prev = None
    while prev != t:
        prev = t
        t = _CONT.sub("", t).strip()
    t = t.casefold().strip(" :-–—")
    return t or None


# ---------------------------------------------------------------- locating quotes


def _ws_insensitive_pattern(needle: str) -> re.Pattern:
    tokens = normalize_ws(needle).split(" ")
    return re.compile(r"\s+".join(re.escape(t) for t in tokens), re.IGNORECASE)


def find_span(haystack: str, needle: str, fuzzy_min: float = 95.0) -> tuple[int, int] | None:
    """Locate `needle` inside `haystack`.

    1. exact substring, 2. whitespace/case-insensitive, 3. fuzzy (partial_ratio >= fuzzy_min).
    Returns (start, end) offsets into `haystack`, or None.
    """
    needle = needle.strip()
    if not needle:
        return None
    i = haystack.find(needle)
    if i >= 0:
        return i, i + len(needle)
    m = _ws_insensitive_pattern(needle).search(haystack)
    if m:
        return m.start(), m.end()
    if len(needle) < 12:
        return None
    al = fuzz.partial_ratio_alignment(needle, haystack)
    if al is None or al.score < fuzzy_min:
        return None
    start, end = al.dest_start, al.dest_end
    # Widen to whole words so the stored quote never starts or ends mid-word.
    while start > 0 and not haystack[start - 1].isspace():
        start -= 1
    while end < len(haystack) and not haystack[end].isspace():
        end += 1
    return start, end


def contains(haystack: str, needle: str) -> bool:
    """Whitespace- and case-insensitive containment."""
    if not needle or not needle.strip():
        return False
    return norm_cmp(needle) in norm_cmp(haystack)


# ---------------------------------------------------------------- extracted items


@dataclass
class ValidatedItem:
    kind: str
    page_no: int
    term: str
    aliases: list[str]
    body: str
    source_quote: str
    quote_start: int
    quote_end: int
    topic: str | None
    topic_key: str | None = None

    def __post_init__(self):
        self.topic_key = topic_key(self.topic)


@dataclass
class Rejection:
    reason: str
    term: str = ""


def validate_item(raw: dict, page_text: str, page_no: int) -> ValidatedItem | Rejection:
    """Snap an extracted item onto the real page text, or reject it (§6.3)."""
    term = normalize_ws(str(raw.get("term") or ""))
    # "The mitochondria" -> "mitochondria": the article is never part of the term.
    stripped = re.sub(r"^(?:the|a|an)\s+", "", term, flags=re.IGNORECASE)
    if stripped and stripped != term:
        term = stripped
    body = normalize_ws(str(raw.get("body") or ""))
    quote = str(raw.get("source_quote") or "")
    kind = raw.get("kind") if raw.get("kind") in ("definition", "fact") else "fact"
    if not term:
        return Rejection("missing_term")
    if not body or len(body) < 4:
        return Rejection("missing_body", term)

    span = find_span(page_text, quote) if quote.strip() else None
    if span is None:
        # The model may have quoted loosely; the body itself is often the real sentence.
        span = find_span(page_text, body)
    if span is None:
        return Rejection("quote_not_in_page", term)
    real_quote = page_text[span[0] : span[1]]

    if not contains(real_quote, term):
        # Allow the term to sit just before the quote on the same page (e.g. a heading line).
        widened = find_span(page_text, term)
        if widened is None or not (widened[0] <= span[1] and widened[1] >= span[0] - 120):
            return Rejection("term_not_in_quote", term)
        start = min(widened[0], span[0])
        end = max(widened[1], span[1])
        span = (start, end)
        real_quote = page_text[start:end]
    if not contains(real_quote, body):
        # Accept a body that is a trimmed version of the quote (bullets / wrapped lines).
        if not contains(clean_for_display(real_quote), body):
            return Rejection("body_not_in_quote", term)

    aliases = []
    for a in raw.get("aliases") or []:
        a = normalize_ws(str(a))
        if a and norm_cmp(a) != norm_cmp(term) and a not in aliases:
            aliases.append(a)

    topic = raw.get("topic")
    topic = normalize_ws(str(topic)) if topic else None
    return ValidatedItem(
        kind=kind,
        page_no=page_no,
        term=term,
        aliases=aliases,
        body=body,
        source_quote=real_quote,
        quote_start=span[0],
        quote_end=span[1],
        topic=topic,
    )


def is_duplicate(a_term: str, a_body: str, b_term: str, b_body: str, min_ratio: float = 90.0) -> bool:
    if norm_cmp(a_term) != norm_cmp(b_term):
        return False
    return fuzz.ratio(norm_cmp(a_body), norm_cmp(b_body)) >= min_ratio


def dedupe_items(items: list[ValidatedItem], existing: list[tuple[str, str, list[str]]] | None = None):
    """Merge items with the same term and a similar body. Returns (kept, merged_aliases_for_existing).

    `existing` = (term, body, aliases) of items already stored for the document; a new item
    that duplicates one of them is dropped (its aliases are returned so they can be merged).
    """
    kept: list[ValidatedItem] = []
    extra_aliases: dict[int, list[str]] = {}
    for it in items:
        dup_existing = None
        for idx, (t, b, _) in enumerate(existing or []):
            if is_duplicate(it.term, it.body, t, b):
                dup_existing = idx
                break
        if dup_existing is not None:
            extra_aliases.setdefault(dup_existing, []).extend(it.aliases)
            continue
        merged = False
        for k in kept:
            if is_duplicate(it.term, it.body, k.term, k.body):
                for a in it.aliases:
                    if a not in k.aliases:
                        k.aliases.append(a)
                merged = True
                break
        if not merged:
            kept.append(it)
    return kept, extra_aliases


# ---------------------------------------------------------------- question checks


def blank_term(text: str, term: str) -> str | None:
    """Replace the first occurrence of `term` (case/whitespace-insensitive) with the blank."""
    m = _ws_insensitive_pattern(term).search(text)
    if not m:
        return None
    return text[: m.start()] + BLANK + text[m.end() :]


def check_identification(prompt: str, body: str, term: str) -> bool:
    if BLANK in prompt:
        restored = prompt.replace(BLANK, term, 1)
        return norm_cmp(restored) == norm_cmp(body) or norm_cmp(prompt) == norm_cmp(blank_term(body, term) or "")
    return norm_cmp(prompt) == norm_cmp(body)


def check_fill_in_stem(stem: str, source_quote: str, term: str) -> bool:
    if stem.count(BLANK) != 1:
        return False
    return norm_cmp(stem.replace(BLANK, term, 1)) == norm_cmp(clean_for_display(source_quote)) or norm_cmp(
        stem.replace(BLANK, term, 1)
    ) == norm_cmp(source_quote)


def check_option_is_lesson_text(option: str, lesson_terms_and_bodies: set[str]) -> bool:
    return norm_cmp(option) in lesson_terms_and_bodies


def check_true_statement(prompt: str, source_quote: str, body: str) -> bool:
    p = norm_cmp(prompt)
    return p in (norm_cmp(source_quote), norm_cmp(clean_for_display(source_quote)), norm_cmp(body))


def _tokens(s: str) -> list[str]:
    return norm_cmp(s).split(" ")


def check_false_statement(false_stmt: str, true_stmt: str, original_span: str, replacement: str) -> bool:
    """Exactly one span changed: the token diff must be confined to original_span -> replacement."""
    if not original_span or not replacement:
        return False
    if norm_cmp(original_span) == norm_cmp(replacement):
        return False
    if not contains(true_stmt, original_span):
        return False
    if norm_cmp(false_stmt) == norm_cmp(true_stmt):
        return False
    expected = _ws_insensitive_pattern(original_span).sub(replacement, true_stmt, count=1)
    if norm_cmp(expected) != norm_cmp(false_stmt):
        return False
    # Common prefix/suffix of tokens must cover everything except the edited region.
    t, f = _tokens(true_stmt), _tokens(false_stmt)
    i = 0
    while i < min(len(t), len(f)) and t[i] == f[i]:
        i += 1
    j = 0
    while j < min(len(t), len(f)) - i and t[-1 - j] == f[-1 - j]:
        j += 1
    changed_true = " ".join(t[i : len(t) - j])
    if changed_true and changed_true not in norm_cmp(original_span) and norm_cmp(original_span) not in changed_true:
        return False
    return fuzz.ratio(norm_cmp(false_stmt), norm_cmp(true_stmt)) >= 70


_QUOTED = re.compile(r"[\"“”]([^\"“”]{3,})[\"“”]|'([^']{6,})'")


def check_rationale(rationale: str, lesson_text_norm: str, forbidden_as_true: str | None = None) -> bool:
    """Non-empty, <= 40 words, grounded, and not contradicting the answer (§9)."""
    r = normalize_ws(rationale or "")
    if not r:
        return False
    if len(r.split(" ")) > 40:
        return False
    if forbidden_as_true and norm_cmp(forbidden_as_true) in norm_cmp(r):
        # The T/F replacement text may only appear if the sentence says it is wrong.
        if not re.search(r"\b(not|wrong|false|incorrect|instead|rather|actually)\b", r, re.IGNORECASE):
            return False
    for m in _QUOTED.finditer(r):
        phrase = m.group(1) or m.group(2)
        if phrase and norm_cmp(phrase) not in lesson_text_norm:
            return False
    return True


def rationale_fallback(source_quote: str) -> str:
    return f"The lesson states: '{clean_for_display(source_quote)}'"


@dataclass
class LessonIndex:
    """What the reviewer's items say, in comparison form, for option and rationale checks."""

    option_texts: set[str] = field(default_factory=set)
    text_norm: str = ""

    @classmethod
    def build(cls, items) -> "LessonIndex":
        opts = set()
        parts = []
        for it in items:
            if it.term:
                opts.add(norm_cmp(it.term))
                parts.append(it.term)
            opts.add(norm_cmp(it.body))
            parts.append(it.body)
            parts.append(it.source_quote)
            for a in it.aliases or []:
                opts.add(norm_cmp(a))
                parts.append(a)
        return cls(option_texts=opts, text_norm=norm_cmp(" \n ".join(parts)))
