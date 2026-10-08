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

from app.models import Document, SourceItem
from app.services.fidelity import (
    BLANK,
    LessonIndex,
    capitalize_first,
    check_fill_in_stem,
    check_option_is_lesson_text,
    clean_for_display,
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


def terms_of(it) -> list[str]:
    return [t for t in [it.term, *(it.aliases or [])] if t]


def meaning_text(it) -> str:
    """A definition as an option: without its own term, every other mention of it blanked."""
    body = strip_term_prefix(clean_for_display(it.body), terms_of(it))
    return capitalize_first(mask_terms(body, terms_of(it)).strip())


def fill_in_stem(it) -> str | None:
    stem = mask_terms(clean_for_display(it.source_quote), terms_of(it))
    if BLANK not in stem or visible_chars(stem) < 8:
        return None
    return stem


def _safe_term_distractor(c, answer_terms: list[str], stem: str) -> bool:
    if not c.term or poor_option(c.term):
        return False
    names = terms_of(c)
    if any(too_close(a, n) for a in answer_terms for n in names):
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
    return norm_cmp(text) != norm_cmp(correct_text) and not too_close(text, correct_text)


def prepare_mcq(d: Draft, pool: list[SourceItem], rng: random.Random) -> Draft:
    """Pick the stem format and the safe candidate distractors. Gemini picks among them later."""
    it = d.item
    if not it.term:
        d.failed = "mcq_no_format"
        return d
    answer_terms = terms_of(it)
    stem = fill_in_stem(it)
    correct_meaning = meaning_text(it) if it.kind == "definition" else ""
    can_fill = stem is not None
    can_meaning = (it.kind == "definition" and visible_chars(correct_meaning) >= MIN_MEANING_CHARS
                   and not mentions(correct_meaning, answer_terms))
    if can_fill and can_meaning:
        fmt = rng.choice(["fill_in", "term_meaning"])
    elif can_fill:
        fmt = "fill_in"
    elif can_meaning:
        fmt = "term_meaning"
    else:
        d.failed = "mcq_no_format"
        return d
    d.mcq_format = fmt

    if fmt == "fill_in":
        d.prompt = stem
        correct_text = capitalize_first(it.term)
        cands = [c for c in pool if c.id != it.id and _safe_term_distractor(c, answer_terms, stem)]
        texts = {c.id: capitalize_first(c.term) for c in cands}
        words = len(it.term.split())
        rank = lambda c: (c.kind != it.kind, not (it.topic_key and c.topic_key == it.topic_key),  # noqa: E731
                          abs(len(c.term.split()) - words), rng.random())
    else:
        d.prompt = f"Which of the following best describes **{it.term}**?"
        correct_text = correct_meaning
        cands = [c for c in pool if c.id != it.id and _safe_meaning_distractor(c, it, correct_text)]
        texts = {c.id: meaning_text(c) for c in cands}
        length = len(correct_text)
        rank = lambda c: (not (it.topic_key and c.topic_key == it.topic_key),  # noqa: E731
                          abs(len(texts[c.id]) - length) // 40, rng.random())

    # Drop candidates whose option text repeats another candidate's.
    seen = {norm_cmp(correct_text)}
    unique = []
    for c in sorted(cands, key=rank):
        key = norm_cmp(texts[c.id])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    # An option with a blank in it stands out next to options without one: avoid it when we can.
    if BLANK not in correct_text:
        plain = [c for c in unique if BLANK not in texts[c.id]]
        if len(plain) >= 3:
            unique = plain
    unique = unique[:40]
    d.candidate_ids = [c.id for c in unique]
    d.candidate_texts = {c.id: texts[c.id] for c in unique}
    d.needs_generated = max(0, 3 - len(unique))
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


def finish_mcq(d: Draft, picked_ids: list[str], generated: list[tuple[str, str]], by_id: dict[str, SourceItem],
               docs: dict[str, Document], index: LessonIndex, rng: random.Random) -> Draft:
    """Attach 3 distractors (lesson items by id, or generated text) and build choice feedback."""
    it = d.item
    distractors: list[dict] = []
    feedback: dict[str, str] = {}
    seen = {norm_cmp(d.choices[0]["text"])}

    def add(c) -> None:
        text = d.candidate_texts.get(c.id)
        if not text or norm_cmp(text) in seen:
            return
        seen.add(norm_cmp(text))
        cid = f"c{len(distractors) + 2}"
        distractors.append({"id": cid, "text": text, "source_item_id": c.id})
        feedback[cid] = _feedback_for(c, d.mcq_format, docs[c.document_id])

    for sid in picked_ids:  # Gemini's picks, but only from the safe candidate list
        if len(distractors) == 3:
            break
        if sid in d.candidate_texts and sid in by_id:
            add(by_id[sid])
    for sid in d.candidate_ids:  # top up in ranked order
        if len(distractors) == 3:
            break
        if sid in by_id:
            add(by_id[sid])
    if len(distractors) < 3 and generated:
        answer_terms = terms_of(it)
        for text, why in generated:
            if len(distractors) == 3:
                break
            text = capitalize_first(normalize_option(text))
            if (not text or norm_cmp(text) in seen or poor_option(text, 6 if d.mcq_format == "fill_in" else 60)
                    or any(too_close(a, text) for a in answer_terms) or mentions(d.prompt, [text])
                    or (d.mcq_format == "term_meaning" and mentions(text, answer_terms))):
                continue
            seen.add(norm_cmp(text))
            cid = f"c{len(distractors) + 2}"
            distractors.append({"id": cid, "text": text, "source_item_id": None})
            feedback[cid] = why or f"{text} is not what the lesson says here."
            d.explanation["generated_distractors"] = True
    if len(distractors) < 3:
        d.failed = "mcq_not_enough_distractors"
        return d
    d.choices = [d.choices[0], *distractors]
    d.choice_feedback = feedback

    # Fidelity (§9) and the no-giveaway rules.
    answer_terms = terms_of(it)
    if d.mcq_format == "fill_in":
        if not check_fill_in_stem(d.prompt, it.source_quote, it.term or ""):
            d.failed = "mcq_stem"
        elif mentions(d.prompt, answer_terms):
            d.failed = "mcq_stem_reveals_answer"
    elif mentions(d.choices[0]["text"], answer_terms):
        d.failed = "mcq_option_reveals_answer"
    for ch in d.choices:
        if ch["source_item_id"] is not None and not check_option_is_lesson_text(ch["text"], index.text_norm):
            d.failed = "mcq_option_not_lesson_text"
    return d


def normalize_option(s: str) -> str:
    return " ".join((s or "").split()).strip(" .")
