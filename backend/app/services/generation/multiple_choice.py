"""Multiple choice: real lesson text for the stem and every option (BACKEND.md §8.3).

The answer must never show through. So:
- every mention of the term (and its aliases, plurals) in the stem is blanked, and "a/an _____"
  becomes "a(n) _____";
- definition options are shown without their own term ("Read – Allows…" -> "Allows…");
- distractors that could also be right (same name, one inside the other, acronym pairs), that are
  named in the stem, or that are numbers / fragments are never offered;
- all options start with a capital letter, so case gives nothing away.
"""

from __future__ import annotations

import random
import re
from itertools import combinations

from rapidfuzz import fuzz

from app.models import Document, SourceItem
from app.services.fidelity import (
    BLANK,
    LessonIndex,
    capitalize_first,
    check_fill_in_stem,
    check_option_is_lesson_text,
    clean_for_display,
    implied_aliases,
    mask_terms,
    mentions,
    norm_cmp,
    poor_option,
    strip_term_prefix,
    too_close,
    visible_chars,
)
from app.services.generation import Draft, source_ref

MIN_MEANING_CHARS = 12

_STOP = set("""a an the and or of to in on for with by as at from into than that this these those its it is are be
can may will not no all any each other such which who whose what when where how your their his her our you
only also used use using new one two three more most default option options called
allow allows within""".split())


def content_words(s: str) -> set[str]:
    """Meaningful words, singular-ish, for spotting a word the question echoes from the answer."""
    out = set()
    for w in re.findall(r"[a-z0-9]+", norm_cmp(s)):
        if len(w) < 3 or w in _STOP:
            continue
        for suffix in ("ing", "ed", "es", "s"):  # "indexing" ~ "index", "screens" ~ "screen"
            if w.endswith(suffix) and len(w) - len(suffix) >= 4:
                w = w[: -len(suffix)]
                break
        out.add(w)
    return out


def terms_of(it) -> list[str]:
    """The answer and every other way the lesson names it (aliases, 'Name (ABBR)' parts)."""
    out: list[str] = []
    for t in [it.term, *(it.aliases or []), *implied_aliases(it.term)]:
        if t and t.casefold() not in {x.casefold() for x in out}:
            out.append(t)
    return out


def meaning_text(it) -> str:
    """A definition as an option: without its own term, every other mention of it blanked."""
    body = strip_term_prefix(clean_for_display(it.body), terms_of(it))
    return capitalize_first(mask_terms(body, terms_of(it)).strip())


def stem_source(it) -> str:
    """The sentence shown with a blank. A definition written as several bullets reads as 'Term – a; b; c.'"""
    if "\n" in it.source_quote.strip():
        return f"{it.term} – {it.body}"
    return clean_for_display(it.source_quote)


def fill_in_stem(it) -> str | None:
    stem = mask_terms(stem_source(it), terms_of(it))
    if BLANK not in stem or visible_chars(stem) < 8:
        return None
    return stem


SAME_MEANING = 92


def same_meaning(a, b) -> bool:
    """Two entries defined (almost) word for word the same, e.g. 'Change' and 'Read/Write'."""
    return fuzz.ratio(norm_cmp(clean_for_display(a.body)), norm_cmp(clean_for_display(b.body))) >= SAME_MEANING


def _safe_term_distractor(c, it, answer_terms: list[str], stem: str) -> bool:
    if not c.term or poor_option(c.term):
        return False
    names = terms_of(c)
    if any(too_close(a, n) for a in answer_terms for n in names):
        return False
    if same_meaning(c, it):  # its definition fits the blank just as well
        return False
    return not mentions(stem, names)  # the stem must not rule it out


def _safe_meaning_distractor(c, it, correct_text: str) -> bool:
    if c.kind != "definition" or not c.term:
        return False
    if any(too_close(a, n) for a in terms_of(it) for n in terms_of(c)):
        return False
    text = meaning_text(c)
    if visible_chars(text) < MIN_MEANING_CHARS or poor_option(text, max_words=60):
        return False
    if mentions(text, terms_of(it)):  # would point at the asked term
        return False
    if same_meaning(c, it):  # would be right too
        return False
    return norm_cmp(text) != norm_cmp(correct_text) and not too_close(text, correct_text)


MAX_LEN_RATIO = 2.2
MIN_CONTENT_WORDS = 2


_REFERENCE_WORDS = {"see", "table", "figure", "shown", "page", "slide", "chapter", "section", "above", "below"}


def enough_words(text: str) -> bool:
    """'_____ – _____ apply (see Table 5-2)' leaves nothing to answer from."""
    words = [w for w in content_words(text.replace(BLANK, " ")) if len(w) >= 4 and w not in _REFERENCE_WORDS]
    return len(words) >= MIN_CONTENT_WORDS


def echo_words(it, fmt: str, stem, correct_text: str) -> set:
    """Words of the answer that the question shows: they must not single out the right option."""
    shown = (stem or "") if fmt == "fill_in" else correct_text
    return content_words(it.term) & content_words(shown.replace(BLANK, " "))


def option_set_ok(correct: str, distractor_texts: list, echo: set) -> bool:
    """No echo word only in the right option (each must be in >= 2 wrong ones), no length outlier."""
    return hint_penalty(correct, distractor_texts, echo) == 0


def hint_penalty(correct: str, distractor_texts: list, echo: set, words: dict | None = None) -> int:
    """How much the option set points at the answer: 0 = nothing. Each echo word missing from the
    wrong options counts, and a right option that stands out by length counts 2."""
    words = words or {}
    sets = [words[t] if t in words else content_words(t) for t in distractor_texts]
    p = sum(max(0, 2 - sum(1 for s in sets if w in s)) for w in echo)
    n = len(correct)
    ls = [len(t) for t in distractor_texts]
    if n > MAX_LEN_RATIO * max(ls) or n * MAX_LEN_RATIO < min(ls):
        p += 2
    return p


def choose_distractors(correct: str, ordered: list, echo: set, limit: int = 16, best_effort: bool = False):
    """First set of 3 (in preference order) that gives nothing away. `ordered` = [(id, text)].
    With `best_effort`, when no such set exists, the set with the smallest hint instead."""
    pool = ordered[:limit]
    for trio in combinations(pool, 3):
        if option_set_ok(correct, [t for _, t in trio], echo):
            return list(trio)
    if not best_effort:
        return None
    pool = ordered[:24]
    words = {t: content_words(t) for _, t in pool}
    best, best_p = None, None
    for trio in combinations(pool, 3):
        p = hint_penalty(correct, [t for _, t in trio], echo, words)
        if best_p is None or p < best_p:
            best, best_p = list(trio), p
    return best


def _candidates(it, fmt: str, pool, stem, correct_text: str, rng: random.Random):
    """Safe candidates for one format, best first. Returns ([(item, option text)], echo words)."""
    answer_terms = terms_of(it)
    echo = echo_words(it, fmt, stem, correct_text)
    if fmt == "fill_in":
        cands = [c for c in pool if c.id != it.id and _safe_term_distractor(c, it, answer_terms, stem)]
        texts = {c.id: capitalize_first(c.term) for c in cands}
    else:
        cands = [c for c in pool if c.id != it.id and _safe_meaning_distractor(c, it, correct_text)]
        texts = {c.id: meaning_text(c) for c in cands}
    length = max(1, len(correct_text))

    def rank(c):
        t = texts[c.id]
        covers = len(echo & content_words(t))
        ratio = max(len(t), length) / max(1, min(len(t), length))
        same_topic = bool(it.topic_key and c.topic_key == it.topic_key)
        return (-covers, ratio > MAX_LEN_RATIO, not same_topic, c.kind != it.kind, round(ratio, 1), rng.random())

    seen = {norm_cmp(correct_text)}
    out = []
    for c in sorted(cands, key=rank):
        key = norm_cmp(texts[c.id])
        if key not in seen:
            seen.add(key)
            out.append((c, texts[c.id]))
    # An option with a blank in it stands out next to options without one: avoid it when we can.
    if BLANK not in correct_text:
        plain = [x for x in out if BLANK not in x[1]]
        if len(plain) >= 3:
            out = plain
    return out[:40], echo


def _has_twin(it, pool) -> bool:
    """Another item with the same name but a different meaning (e.g. 'Read' in two permission lists)."""
    return any(c.id != it.id and c.term and norm_cmp(c.term) == norm_cmp(it.term)
               and norm_cmp(c.body) != norm_cmp(it.body) for c in pool)


def prepare_mcq(d: Draft, pool: list, rng: random.Random, prefer_meaning: bool = False) -> Draft:
    """Pick a stem format whose options can be hint-free, plus the safe candidates. Gemini picks among them later.

    With `d.best_effort` the item is never dropped for a hint: weaker formats are allowed and, when no
    hint-free set exists, the format whose best option set hints the least wins. `prefer_meaning` asks
    "Which best describes X?" first (used when another item in the set has the same definition, so the
    same fill-in sentence won't appear twice with two different answers)."""
    it = d.item
    if not it.term:
        d.failed = "mcq_no_format"
        return d
    answer_terms = terms_of(it)
    stem = fill_in_stem(it)
    correct_meaning = meaning_text(it) if it.kind == "definition" else ""
    formats = []
    # numbers / long phrases stand out as answers; a stem needs enough real words to be answerable
    if stem is not None and not poor_option(it.term) and enough_words(stem):
        formats.append("fill_in")
    if (it.kind == "definition" and visible_chars(correct_meaning) >= MIN_MEANING_CHARS
            and not mentions(correct_meaning, answer_terms) and enough_words(correct_meaning)):
        formats.append("term_meaning")
    if not formats and d.best_effort:
        if stem is not None:
            formats.append("fill_in")
        if (it.kind == "definition" and visible_chars(correct_meaning) >= MIN_MEANING_CHARS
                and not mentions(correct_meaning, answer_terms)):
            formats.append("term_meaning")
    if not formats:
        d.failed = "mcq_no_format"
        return d
    rng.shuffle(formats)
    if prefer_meaning and "term_meaning" in formats:
        formats.remove("term_meaning")
        formats.insert(0, "term_meaning")

    chosen = None
    tried = []
    for fmt in formats:
        correct_text = capitalize_first(it.term) if fmt == "fill_in" else correct_meaning
        ranked, echo = _candidates(it, fmt, pool, stem, correct_text, rng)
        # a twin is asked by name even if that leaves a small hint: the same fill-in sentence with two answers is worse
        lenient = d.best_effort and prefer_meaning and fmt == "term_meaning"
        if choose_distractors(correct_text, [(c.id, t) for c, t in ranked], echo, best_effort=lenient):
            chosen = (fmt, correct_text, ranked, echo)
            break
        tried.append((fmt, correct_text, ranked, echo))
    if chosen is None and d.best_effort:
        scored = []
        for k, (fmt, correct_text, ranked, echo) in enumerate(tried):
            trio = choose_distractors(correct_text, [(c.id, t) for c, t in ranked], echo, best_effort=True)
            if trio:
                scored.append((hint_penalty(correct_text, [t for _, t in trio], echo), k))
        if scored:
            chosen = tried[min(scored)[1]]
    if chosen is None:
        d.failed = "mcq_hint_unavoidable"
        return d
    fmt, correct_text, ranked, echo = chosen
    d.mcq_format = fmt
    if fmt == "fill_in":
        d.prompt = stem
    else:
        context = f" ({it.topic})" if it.topic and _has_twin(it, pool) else ""
        d.prompt = f"Which of the following best describes **{it.term}**{context}?"
    d.candidate_ids = [c.id for c, _ in ranked]
    d.candidate_texts = {c.id: t for c, t in ranked}
    d.echo_words = sorted(echo)
    d.needs_generated = 0
    d.choices = [{"id": "c1", "text": correct_text, "source_item_id": it.id}]
    d.correct_answer = "c1"
    d.explanation = {"source_quote": it.source_quote, "document_id": it.document_id, "page_no": it.page_no,
                     "changed_span": None, "format": fmt, "generated_distractors": False}
    return d


def _feedback_for(c, fmt: str, doc: Document) -> str:
    where = source_ref(doc, c.page_no)
    if fmt == "fill_in":
        return f"{c.term}: {clean_for_display(c.body)} ({where})"
    return f"That describes {c.term} ({where})."


def finish_mcq(d: Draft, picked_ids: list, generated: list, by_id: dict,
               docs: dict, index: LessonIndex, rng: random.Random) -> Draft:
    """Attach 3 distractors and their feedback. Gemini's picks come first, but the set must give nothing away."""
    it = d.item
    correct = d.choices[0]["text"]
    order: list = []
    for sid in [*picked_ids, *d.candidate_ids]:
        if sid in d.candidate_texts and sid in by_id and sid not in order:
            order.append(sid)
    trio = choose_distractors(correct, [(sid, d.candidate_texts[sid]) for sid in order], set(d.echo_words),
                              best_effort=d.best_effort)
    if trio is None:
        d.failed = "mcq_hint_unavoidable"
        return d
    distractors, feedback = [], {}
    for k, (sid, text) in enumerate(trio):
        c = by_id[sid]
        cid = f"c{k + 2}"
        distractors.append({"id": cid, "text": text, "source_item_id": c.id})
        feedback[cid] = _feedback_for(c, d.mcq_format, docs[c.document_id])
    d.choices = [d.choices[0], *distractors]
    d.choice_feedback = feedback

    # Fidelity (§9) and the no-giveaway rules, checked once more on the final question.
    answer_terms = terms_of(it)
    if d.mcq_format == "fill_in":
        if not check_fill_in_stem(d.prompt, it.source_quote + "\n" + stem_source(it), it.term or ""):
            d.failed = "mcq_stem"
        elif mentions(d.prompt, answer_terms):
            d.failed = "mcq_stem_reveals_answer"
        elif any(mentions(d.prompt, [x["text"]]) for x in distractors):
            d.failed = "mcq_stem_names_option"
    elif mentions(correct, answer_terms):
        d.failed = "mcq_option_reveals_answer"
    for ch in d.choices:
        if not check_option_is_lesson_text(ch["text"], index.text_norm):
            d.failed = "mcq_option_not_lesson_text"
    return d


def normalize_option(s: str) -> str:
    return " ".join((s or "").split()).strip(" .")
