"""Printable exam with an optional answer key (BACKEND.md §11.1)."""

from __future__ import annotations

from datetime import date

from app.models import Document, Exam
from app.services.export import TYPE_INSTRUCTION, TYPE_LABEL, ReviewerPDF
from app.services.fidelity import clean_for_display
from app.services.generation import TYPE_ORDER, source_ref

ROMAN = ["I", "II", "III"]


def exam_pdf(exam: Exam, docs: dict[str, Document], with_answer_key: bool = True) -> bytearray:
    pdf = ReviewerPDF()
    pdf.add_page()
    pdf.set_font("Noto", "B", 16)
    pdf.multi_cell(0, 8, exam.reviewer.title, new_x="LMARGIN", new_y="NEXT")
    pdf.text_line(f"{date.today():%B %d, %Y}   ·   {exam.actual_count} items", size=10)
    pdf.ln(2)
    pdf.text_line("Name: ______________________________________        Score: ________ / " + str(exam.actual_count), size=10.5)
    pdf.rule()

    questions = sorted(exam.questions, key=lambda q: (TYPE_ORDER[q.type], q.position))
    types_present = [t for t in TYPE_ORDER if any(q.type == t for q in questions)]
    number = 0
    key_rows: list[tuple[int, str, str, str]] = []
    for part_idx, t in enumerate(types_present):
        pdf.heading(f"Part {ROMAN[part_idx]} – {TYPE_LABEL[t]}")
        pdf.text_line(TYPE_INSTRUCTION[t], size=9.5)
        pdf.ln(1)
        for q in [x for x in questions if x.type == t]:
            number += 1
            prompt = q.prompt.replace("**", "")
            pdf.text_line(f"{number}. {prompt}", size=10.5)
            if t == "mcq":
                letters = "ABCD"
                for k, ch in enumerate(q.choices or []):
                    pdf.text_line(f"{letters[k]}. {ch['text']}", size=10, indent=8, h=5.2)
                correct_letter = next((letters[k] for k, ch in enumerate(q.choices or []) if ch["id"] == q.correct_answer), "?")
                answer = f"{correct_letter}. {next((c['text'] for c in q.choices if c['id'] == q.correct_answer), '')}"
            elif t == "true_false":
                pdf.text_line("Answer: ________", size=9.5, indent=8, h=5)
                answer = q.correct_answer.upper()
            else:
                pdf.text_line("Answer: ______________________________", size=9.5, indent=8, h=5)
                answer = q.correct_answer
            pdf.ln(1.5)
            exp = q.explanation or {}
            doc = docs.get(exp.get("document_id"))
            src = source_ref(doc, exp.get("page_no")) if doc and exp.get("page_no") else ""
            key_rows.append((number, answer, clean_for_display(q.rationale), src))
        pdf.ln(2)

    if with_answer_key:
        pdf.add_page()
        pdf.heading("Answer Key", size=14)
        for n, ans, why, src in key_rows:
            pdf.text_line(f"{n}. {ans}", size=10.5, bold=True)
            if why:
                pdf.text_line(why, size=9.5, indent=6, h=5)
            if src:
                pdf.set_text_color(100)
                pdf.text_line(src, size=8.5, indent=6, h=4.5)
                pdf.set_text_color(0)
            pdf.ln(1)
    return pdf.output()
