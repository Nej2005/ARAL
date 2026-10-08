"""Identification questions: deterministic, no LLM (BACKEND.md §8.2)."""

from __future__ import annotations

from app.services.fidelity import BLANK, blank_term, check_identification, clean_for_display
from app.services.generation import Draft


def build_identification(d: Draft) -> Draft:
    it = d.item
    body = clean_for_display(it.body)
    prompt = blank_term(body, it.term or "") or body
    if prompt.strip() in (BLANK, ""):
        prompt = body
    d.prompt = prompt
    d.correct_answer = it.term or ""
    d.accepted_answers = [it.term, *[a for a in (it.aliases or []) if a]]
    d.explanation = {"source_quote": it.source_quote, "document_id": it.document_id, "page_no": it.page_no,
                     "changed_span": None}
    if not check_identification(d.prompt, body, it.term or ""):
        d.failed = "identification_prompt"
    return d
