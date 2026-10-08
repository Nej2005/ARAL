"""True / False: a verbatim statement, or the same statement with exactly one span changed (§8.4)."""

from __future__ import annotations

from app.services.fidelity import check_false_statement, check_true_statement, clean_for_display, contains, norm_cmp
from app.services.generation import Draft


def statement_text(d: Draft) -> str:
    it = d.item
    q = clean_for_display(it.source_quote)
    # Very long quotes make poor statements; the body is the sentence itself.
    if len(q) > 260 and len(it.body) < len(q):
        return clean_for_display(it.body)
    return q


def build_true(d: Draft) -> Draft:
    it = d.item
    d.prompt = statement_text(d)
    d.is_true = True
    d.correct_answer = "true"
    d.explanation = {"source_quote": it.source_quote, "document_id": it.document_id, "page_no": it.page_no,
                     "changed_span": None}
    if not check_true_statement(d.prompt, it.source_quote, it.body):
        d.failed = "tf_true_statement"
    return d


def build_false(d: Draft, original_span: str, replacement: str, reason: str, other_statements: set[str]) -> Draft:
    it = d.item
    true_stmt = statement_text(d)
    original_span = (original_span or "").strip()
    replacement = (replacement or "").strip()
    d.is_true = False
    d.correct_answer = "false"
    d.explanation = {"source_quote": it.source_quote, "document_id": it.document_id, "page_no": it.page_no,
                     "changed_span": {"from": original_span, "to": replacement}, "reason": reason}
    if not original_span or not replacement or not contains(true_stmt, original_span):
        d.failed = "tf_span_missing"
        return d
    # Build the false statement ourselves: everything else stays exactly as in the source.
    idx = true_stmt.find(original_span)
    if idx < 0:
        low = norm_cmp(true_stmt)
        idx = low.find(norm_cmp(original_span))
        if idx < 0:
            d.failed = "tf_span_missing"
            return d
        false_stmt = true_stmt[:idx] + replacement + true_stmt[idx + len(original_span):]
    else:
        false_stmt = true_stmt[:idx] + replacement + true_stmt[idx + len(original_span):]
    d.prompt = false_stmt
    if norm_cmp(false_stmt) in other_statements:
        d.failed = "tf_accidentally_true"
        return d
    if not check_false_statement(false_stmt, true_stmt, original_span, replacement):
        d.failed = "tf_false_statement"
    return d
