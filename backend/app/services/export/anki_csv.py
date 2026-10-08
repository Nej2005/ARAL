"""Anki-importable CSV (BACKEND.md §11.3)."""

from __future__ import annotations

import csv
import html
import io
import re

from app.models import Document, Exam, Reviewer, SourceItem
from app.services.fidelity import BLANK, blank_term, clean_for_display
from app.services.generation import source_ref

TYPE_TAG = {"mcq": "mcq", "true_false": "tf", "identification": "ident"}


def _slug(s: str) -> str:
    s = re.sub(r"[^\w]+", "-", (s or "").strip().casefold()).strip("-")
    return s or "untitled"


def _h(s: str) -> str:
    return html.escape(s or "", quote=False).replace("\n", "<br>")


def _header(deck: str) -> str:
    return (
        "#separator:comma\n#html:true\n#notetype:Basic\n"
        f"#deck:ARAL::{deck}\n#columns:Front,Back,Tags\n#tags column:3\n"
    )


def _write(rows: list[tuple[str, str, str]], deck: str) -> str:
    buf = io.StringIO()
    buf.write(_header(deck))
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def exam_csv(exam: Exam, docs: dict[str, Document]) -> str:
    r = exam.reviewer
    rows = []
    for q in sorted(exam.questions, key=lambda q: q.position):
        exp = q.explanation or {}
        doc = docs.get(exp.get("document_id"))
        src = source_ref(doc, exp.get("page_no")) if doc and exp.get("page_no") else ""
        front = _h(q.prompt.replace("**", ""))
        if q.type == "mcq":
            letters = "ABCD"
            front += "<br>" + "<br>".join(f"{letters[k]}. {_h(c['text'])}" for k, c in enumerate(q.choices or []))
            correct = next((f"{letters[k]}. {c['text']}" for k, c in enumerate(q.choices or []) if c["id"] == q.correct_answer), "")
        elif q.type == "true_false":
            correct = q.correct_answer.upper()
        else:
            correct = q.correct_answer
        back = _h(correct) + "<br><br>" + _h(clean_for_display(q.rationale)) + (f"<br><i>{_h(src)}</i>" if src else "")
        tags = ["aral", f"reviewer::{_slug(r.title)}", f"type::{TYPE_TAG[q.type]}"]
        if doc:
            tags.append(f"file::{_slug(doc.filename)}")
        if q.source_item and q.source_item.topic_key:
            tags.append(f"topic::{_slug(q.source_item.topic_key)}")
        rows.append((front, back, " ".join(tags)))
    return _write(rows, r.title)


def items_csv(reviewer: Reviewer, items: list[SourceItem], docs: dict[str, Document]) -> str:
    rows = []
    for it in items:
        doc = docs.get(it.document_id)
        src = source_ref(doc, it.page_no) if doc else ""
        body = clean_for_display(it.body)
        if it.kind == "definition" and it.term:
            front, back = it.term, body
        else:
            stem = blank_term(body, it.term or "") if it.term else None
            front = stem if stem and stem.count(BLANK) == 1 else body
            back = it.term or body
        tags = ["aral", f"reviewer::{_slug(reviewer.title)}"]
        if doc:
            tags.append(f"file::{_slug(doc.filename)}")
        if it.topic_key:
            tags.append(f"topic::{_slug(it.topic_key)}")
        rows.append((_h(front), _h(back) + (f"<br><i>{_h(src)}</i>" if src else ""), " ".join(tags)))
    return _write(rows, reviewer.title)
