"""PDF -> pages, keeping the original wording and line breaks (BACKEND.md §5.2)."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pymupdf

from app.services.ingestion import ExtractedPage

_HYPHEN_BREAK = re.compile(r"(\w)-\n(?=[a-z])")
_WS = re.compile(r"\s+")


def _norm_line(s: str) -> str:
    return _WS.sub(" ", s).strip().casefold()


def _repeated_edges(pages: list[list[str]]) -> tuple[set[str], set[str]]:
    """Lines that open / close more than half of the pages are headers / footers."""
    if len(pages) < 3:
        return set(), set()
    firsts = Counter(_norm_line(p[0]) for p in pages if p)
    lasts = Counter(_norm_line(p[-1]) for p in pages if p)
    limit = len(pages) / 2
    heads = {l for l, n in firsts.items() if n > limit and not re.fullmatch(r"\d+", l)}
    foots = {l for l, n in lasts.items() if n > limit}
    # Pure page numbers in the footer are dropped regardless of their count.
    return heads, foots


def extract_pdf(path: str | Path) -> list[ExtractedPage]:
    doc = pymupdf.open(str(path))
    raw_pages: list[list[str]] = []
    for page in doc:
        text = page.get_text("text", sort=True)
        text = _HYPHEN_BREAK.sub(r"\1", text)
        lines = [l.rstrip() for l in text.split("\n")]
        # Drop empty leading/trailing lines; keep inner blank lines (paragraph breaks).
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        raw_pages.append(lines)
    doc.close()

    heads, foots = _repeated_edges(raw_pages)
    out: list[ExtractedPage] = []
    for i, lines in enumerate(raw_pages, start=1):
        if lines and _norm_line(lines[0]) in heads:
            lines = lines[1:]
        if lines and (_norm_line(lines[-1]) in foots or re.fullmatch(r"\s*(page\s*)?\d+\s*(of\s*\d+)?\s*", lines[-1], re.I)):
            lines = lines[:-1]
        while lines and not lines[0].strip():
            lines.pop(0)
        text = "\n".join(lines)
        title = None
        if lines:
            first = lines[0].strip()
            if 2 <= len(first) <= 80 and len(lines) > 1 and not first.endswith((".", ",", ";", ":")):
                title = first
        out.append(ExtractedPage(page_no=i, title=title, text=text))
    return out
