"""Pages -> source items with Gemini, validated against the page text (BACKEND.md §6)."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Document, DocumentPage, SourceItem, utcnow
from app.services import llm
from app.services.fidelity import Rejection, ValidatedItem, dedupe_items, validate_item

log = logging.getLogger("aral.knowledge")

# Bump when the prompt or the validation rules change; documents show `outdated: true`.
EXTRACTION_VERSION = 1


class ExtractedItem(BaseModel):
    kind: Literal["definition", "fact"]
    page_no: int
    term: str = Field(description="The term being defined, or the key term of the fact.")
    aliases: list[str] = Field(default_factory=list, description="Other names for the term that appear IN THE DOCUMENT.")
    body: str = Field(description="The definition text, or the full factual statement.")
    source_quote: str = Field(description="Copied character-for-character from the page text.")
    topic: str | None = Field(default=None, description="Slide title / section heading, as written.")


class ExtractionResult(BaseModel):
    items: list[ExtractedItem]


EXTRACTION_RULES = """You extract reviewable facts from lesson material for an exam reviewer.

You receive the text of several pages/slides. Each page starts with a line like
=== PAGE 4 | Title ===

Return every distinct DEFINITION and FACT a student should memorize.
- kind "definition": a term with its meaning (e.g. "Photosynthesis is the process by which ...",
  "Term – meaning", "Term: meaning", or a table row "term | meaning").
- kind "fact": a specific statement worth testing (e.g. "The mitochondria is known as the powerhouse of the cell.").
  Its `term` is the key noun or value the statement is about.

STRICT RULES
1. Copy `source_quote`, `term` and `body` VERBATIM from the page text. Never paraphrase, fix grammar,
   expand abbreviations, or summarize. Keep the original capitalization and punctuation.
2. `term` and `body` must both be substrings of `source_quote`. `source_quote` is one contiguous span of
   the page text (it may span a few lines).
3. One item per distinct definition or fact. Do not repeat an item that appears on two pages.
4. `aliases` may only contain other names that actually appear in the document (e.g. "CPU" for
   "Central Processing Unit"). Otherwise leave it empty.
5. `page_no` is the number from the === PAGE n === line where the quote is.
6. `topic` is that page's title/heading, as written, or null.
7. Skip: opinions, examples, exercises, instructions, learning objectives, tables of contents, references,
   title-only pages, and "Thank you / Questions?" pages.
8. If there is nothing to extract, return {"items": []}.
"""


def _windows(pages: list[DocumentPage], size: int) -> list[list[DocumentPage]]:
    """Consecutive windows with a 1-page overlap, e.g. [1..15], [15..29], ..."""
    if not pages:
        return []
    size = max(2, size)
    out, start = [], 0
    while start < len(pages):
        out.append(pages[start : start + size])
        if start + size >= len(pages):
            break
        start += size - 1
    return out


def _window_text(pages: list[DocumentPage]) -> str:
    parts = []
    for p in pages:
        head = f"=== PAGE {p.page_no}" + (f" | {p.title}" if p.title else "") + " ==="
        parts.append(head + "\n" + (p.text or "").rstrip())
    return "\n\n".join(parts)


def _existing_triples(db: Session, doc_id: str) -> list[tuple[SourceItem, str, str, list[str]]]:
    rows = db.query(SourceItem).filter(SourceItem.document_id == doc_id, SourceItem.superseded_at.is_(None)).all()
    return [(r, r.term or "", r.body, list(r.aliases or [])) for r in rows]


def extract_items(db: Session, doc: Document) -> int:
    """Run extraction from `doc.extraction_progress` onward. Returns items added.

    Items are committed after every window so a quota stop can resume later.
    Raises llm.LLMError / llm.LLMQuotaExceeded; the caller sets the document status.
    """
    pages = db.query(DocumentPage).filter(DocumentPage.document_id == doc.id).order_by(DocumentPage.page_no).all()
    by_no = {p.page_no: p for p in pages}
    windows = _windows(pages, settings.extraction_window_pages)
    added = 0
    for w_idx, window in enumerate(windows):
        if w_idx < doc.extraction_progress:
            continue
        if not any((p.text or "").strip() for p in window):
            doc.extraction_progress = w_idx + 1
            db.commit()
            continue
        text = _window_text(window)
        result = _extract_window(text, label=f"extract doc={doc.id[:8]} win={w_idx + 1}/{len(windows)}")

        validated: list[ValidatedItem] = []
        allowed_pages = {p.page_no for p in window}
        for raw in result.items:
            raw_d = raw.model_dump()
            page_no = raw.page_no if raw.page_no in allowed_pages else window[0].page_no
            page = by_no.get(page_no)
            if page is None:
                continue
            v = validate_item(raw_d, page.text, page_no)
            if isinstance(v, Rejection):
                # Try the other pages in the window: the model sometimes mislabels the page.
                for alt in window:
                    if alt.page_no == page_no:
                        continue
                    v2 = validate_item(raw_d, alt.text, alt.page_no)
                    if isinstance(v2, ValidatedItem):
                        v = v2
                        break
            if isinstance(v, Rejection):
                log.info("dropped item (%s): %r", v.reason, (v.term or raw.term)[:60])
                continue
            validated.append(v)

        existing = _existing_triples(db, doc.id)
        kept, merged = dedupe_items(validated, [(t, b, a) for _, t, b, a in existing])
        for idx, aliases in merged.items():
            row = existing[idx][0]
            cur = list(row.aliases or [])
            for a in aliases:
                if a not in cur and a != row.term:
                    cur.append(a)
            row.aliases = cur
        for v in kept:
            db.add(SourceItem(
                document_id=doc.id, page_no=v.page_no, kind=v.kind, term=v.term, aliases=v.aliases,
                body=v.body, source_quote=v.source_quote, quote_start=v.quote_start, quote_end=v.quote_end,
                topic=v.topic, topic_key=v.topic_key,
            ))
            added += 1
        doc.extraction_progress = w_idx + 1
        db.commit()
    return added


def _extract_window(text: str, label: str) -> ExtractionResult:
    try:
        return llm.generate_structured(EXTRACTION_RULES, text, ExtractionResult, label)
    except llm.LLMBlocked:
        # Split the window in half and try each part once (§13.3).
        blocks = text.split("\n\n=== PAGE ")
        if len(blocks) < 2:
            raise
        mid = len(blocks) // 2
        left = "\n\n=== PAGE ".join(blocks[:mid])
        right = "=== PAGE " + "\n\n=== PAGE ".join(blocks[mid:])
        items = []
        for part, tag in ((left, "a"), (right, "b")):
            try:
                items.extend(llm.generate_structured(EXTRACTION_RULES, part, ExtractionResult, label + tag).items)
            except llm.LLMBlocked as e:
                log.warning("window part %s still blocked: %s", tag, e)
        return ExtractionResult(items=items)


def copy_items(db: Session, src: Document, dest: Document) -> int:
    n = 0
    for it in db.query(SourceItem).filter(SourceItem.document_id == src.id, SourceItem.superseded_at.is_(None)):
        db.add(SourceItem(
            document_id=dest.id, page_no=it.page_no, kind=it.kind, term=it.term, aliases=list(it.aliases or []),
            body=it.body, source_quote=it.source_quote, quote_start=it.quote_start, quote_end=it.quote_end,
            topic=it.topic, topic_key=it.topic_key,
        ))
        n += 1
    return n


def supersede_items(db: Session, doc: Document) -> None:
    now = utcnow()
    for it in db.query(SourceItem).filter(SourceItem.document_id == doc.id, SourceItem.superseded_at.is_(None)):
        it.superseded_at = now
