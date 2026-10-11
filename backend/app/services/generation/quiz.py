"""Questions from an answer-key quiz: copied as written, in the quiz's order, with its choices in order."""

from __future__ import annotations

from app.services.generation import Draft


def build_from_answer_key(d: Draft) -> Draft:
    it = d.item
    key = it.answer_key or {}
    d.verbatim = True
    d.prompt = it.body
    d.rationale = ""  # an answer key gives the answer, not the reason
    d.explanation = {"source_quote": it.source_quote, "document_id": it.document_id, "page_no": it.page_no,
                     "changed_span": None, "format": "answer_key", "fixed_order": True,
                     "quiz_no": key.get("number")}
    if key.get("type") == "true_false":
        d.is_true = key.get("answer") == "true"
        d.correct_answer = key.get("answer") or ""
        if d.correct_answer not in ("true", "false"):
            d.failed = "quiz_no_answer"
        return d
    choices = key.get("choices") or []
    right = key.get("correct") or []
    if len(choices) < 2 or not right:
        d.failed = "quiz_no_answer"
        return d
    d.choices = [{"id": f"c{k + 1}", "text": text, "source_item_id": it.id} for k, text in enumerate(choices)]
    d.correct_answer = f"c{right[0] + 1}"
    d.accepted_answers = [f"c{k + 1}" for k in right]
    return d
