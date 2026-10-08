"""Multiple choice: real lesson text for the stem and every option (BACKEND.md §8.3)."""

from __future__ import annotations

import random

from app.models import Document, SourceItem
from app.services.fidelity import (
    BLANK,
    LessonIndex,
    blank_term,
    check_fill_in_stem,
    check_option_is_lesson_text,
    clean_for_display,
    norm_cmp,
)
from app.services.generation import Draft, source_ref


def prepare_mcq(d: Draft, pool: list[SourceItem], rng: random.Random) -> Draft:
    """Pick the stem format and the candidate distractor pool. Distractors are chosen later."""
    it = d.item
    quote = clean_for_display(it.source_quote)
    stem = blank_term(quote, it.term or "") if it.term else None
    can_fill = bool(stem) and stem.count(BLANK) == 1 and len(quote) > len(it.term or "") + 8
    can_meaning = it.kind == "definition" and bool(it.term)
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
        correct_text = it.term
        cands = [c for c in pool if c.id != it.id and c.term and norm_cmp(c.term) != norm_cmp(it.term)]
    else:
        d.prompt = f"Which of the following best describes **{it.term}**?"
        correct_text = clean_for_display(it.body)
        cands = [c for c in pool if c.id != it.id and c.kind == "definition" and norm_cmp(c.body) != norm_cmp(it.body)]
    # Same topic first so Gemini sees the most plausible candidates even if we cap the list.
    same_topic = [c for c in cands if it.topic_key and c.topic_key == it.topic_key]
    other = [c for c in cands if c not in same_topic]
    rng.shuffle(same_topic)
    rng.shuffle(other)
    cands = (same_topic + other)[:40]
    d.candidate_ids = [c.id for c in cands]
    d.needs_generated = max(0, 3 - len(cands))
    d.choices = [{"id": "c1", "text": correct_text, "source_item_id": it.id}]
    d.correct_answer = "c1"
    d.explanation = {"source_quote": it.source_quote, "document_id": it.document_id, "page_no": it.page_no,
                     "changed_span": None, "format": fmt, "generated_distractors": False}
    return d


def finish_mcq(d: Draft, picked_ids: list[str], generated: list[tuple[str, str]], by_id: dict[str, SourceItem],
               docs: dict[str, Document], index: LessonIndex, rng: random.Random) -> Draft:
    """Attach 3 distractors (lesson items by id, or generated text) and build choice feedback."""
    it = d.item
    distractors: list[dict] = []
    feedback: dict[str, str] = {}
    seen = {norm_cmp(d.choices[0]["text"])}
    for sid in picked_ids:
        c = by_id.get(sid)
        if c is None or c.id == it.id or sid not in d.candidate_ids:
            continue
        text = c.term if d.mcq_format == "fill_in" else clean_for_display(c.body)
        if not text or norm_cmp(text) in seen:
            continue
        seen.add(norm_cmp(text))
        doc = docs[c.document_id]
        cid = f"c{len(distractors) + 2}"
        distractors.append({"id": cid, "text": text, "source_item_id": c.id})
        if d.mcq_format == "fill_in":
            feedback[cid] = f"{c.term}: {clean_for_display(c.body)} ({source_ref(doc, c.page_no)})"
        else:
            feedback[cid] = f"That describes {c.term} ({source_ref(doc, c.page_no)})."
        if len(distractors) == 3:
            break
    # Deterministic top-up from the candidate list when Gemini picked too few / invalid ids.
    if len(distractors) < 3:
        rest = [by_id[x] for x in d.candidate_ids if x in by_id and x not in picked_ids]
        rng.shuffle(rest)
        for c in rest:
            text = c.term if d.mcq_format == "fill_in" else clean_for_display(c.body)
            if not text or norm_cmp(text) in seen:
                continue
            seen.add(norm_cmp(text))
            doc = docs[c.document_id]
            cid = f"c{len(distractors) + 2}"
            distractors.append({"id": cid, "text": text, "source_item_id": c.id})
            feedback[cid] = (f"{c.term}: {clean_for_display(c.body)} ({source_ref(doc, c.page_no)})"
                             if d.mcq_format == "fill_in" else f"That describes {c.term} ({source_ref(doc, c.page_no)}).")
            if len(distractors) == 3:
                break
    if len(distractors) < 3 and generated:
        for text, why in generated:
            if not text or norm_cmp(text) in seen:
                continue
            seen.add(norm_cmp(text))
            cid = f"c{len(distractors) + 2}"
            distractors.append({"id": cid, "text": text, "source_item_id": None})
            feedback[cid] = why or f"{text} is not what the lesson says here."
            d.explanation["generated_distractors"] = True
            if len(distractors) == 3:
                break
    if len(distractors) < 3:
        d.failed = "mcq_not_enough_distractors"
        return d
    d.choices = [d.choices[0], *distractors]
    d.choice_feedback = feedback
    # Fidelity (§9)
    if d.mcq_format == "fill_in" and not check_fill_in_stem(d.prompt, it.source_quote, it.term or ""):
        d.failed = "mcq_stem"
    if d.mcq_format == "term_meaning" and norm_cmp(d.choices[0]["text"]) != norm_cmp(clean_for_display(it.body)):
        d.failed = "mcq_correct_option"
    if not d.explanation.get("generated_distractors"):
        for ch in d.choices:
            if not check_option_is_lesson_text(ch["text"], index.option_texts):
                d.failed = "mcq_option_not_lesson_text"
    return d
