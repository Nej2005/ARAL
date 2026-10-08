"""Identification questions: deterministic, no LLM (BACKEND.md §8.2).

The prompt is the definition from the lesson, shown without its own term ("Read – Allows…" ->
"Allows…") and with every other mention of the term or its aliases blanked.
"""

from __future__ import annotations

from app.services.fidelity import capitalize_first, check_identification, clean_for_display, mask_terms, strip_term_prefix
from app.services.generation import Draft


def build_identification(d: Draft) -> Draft:
    it = d.item
    names = [t for t in [it.term, *(it.aliases or [])] if t]
    body = strip_term_prefix(clean_for_display(it.body), names)
    d.prompt = capitalize_first(mask_terms(body, names))
    d.correct_answer = it.term or ""
    d.accepted_answers = list(names)
    d.explanation = {"source_quote": it.source_quote, "document_id": it.document_id, "page_no": it.page_no,
                     "changed_span": None}
    if not check_identification(d.prompt, it.body, it.term or ""):
        d.failed = "identification_prompt"
    return d
