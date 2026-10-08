"""Study sheet: every item, grouped file -> topic, verbatim (BACKEND.md §11.2)."""

from __future__ import annotations

from datetime import date

from app.models import Document, Reviewer, SourceItem
from app.services.export import ReviewerPDF
from app.services.fidelity import clean_for_display


def study_sheet_pdf(reviewer: Reviewer, items: list[SourceItem], docs: dict[str, Document]) -> bytearray:
    pdf = ReviewerPDF()
    pdf.add_page()
    pdf.set_font("Noto", "B", 16)
    pdf.multi_cell(0, 8, reviewer.title, new_x="LMARGIN", new_y="NEXT")
    pdf.text_line(f"Study sheet   ·   {date.today():%B %d, %Y}   ·   {len(items)} items", size=10)
    pdf.rule()

    by_doc: dict[str, list[SourceItem]] = {}
    for it in items:
        by_doc.setdefault(it.document_id, []).append(it)
    for doc in reviewer.documents:
        rows = by_doc.get(doc.id)
        if not rows:
            continue
        pdf.heading(doc.filename, size=13)
        rows.sort(key=lambda i: (i.page_no, i.quote_start))
        current_topic = object()
        for it in rows:
            if it.topic_key != current_topic:
                current_topic = it.topic_key
                if it.topic:
                    pdf.text_line(it.topic, size=11, bold=True)
            where = doc.page_label(it.page_no)
            if it.kind == "definition" and it.term:
                pdf.set_font("Noto", "B", 10.5)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(0, 5.5, f"{it.term} — {clean_for_display(it.body)}  ({where})",
                               new_x="LMARGIN", new_y="NEXT", markdown=False)
                # Re-render: term bold, rest regular, by writing the term then continuing on the same line.
            else:
                pdf.text_line(f"• {clean_for_display(it.body)}  ({where})", size=10.5, indent=2)
            pdf.ln(0.8)
        pdf.ln(2)
    return pdf.output()
