"""Markdown / plain-text term lists -> sections (pages) + glossary entries (BACKEND.md §5.2).

A term list like
    ## Shared Folders
    - **Read** - Allows groups or users to read and execute files.
    - **Archive Attribute**
        - Folder or file needs to be backed up
is read without the LLM: every "**Term** - definition" bullet becomes a definition item, word for word.
Each "##"/"###" heading starts a new section; the heading is the section title (and the topic).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.ingestion import ExtractedPage

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
BOLD_TERM = re.compile(r"^\*\*(.+?)\*\*\s*(?:[-–—:]\s*(.*))?$")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_SKIP_SUB = re.compile(r"^applies to\s*:", re.IGNORECASE)
MAX_SPLIT_WORDS = 6


@dataclass
class GlossaryEntry:
    page_no: int
    term: str
    body: str
    quote: str  # exact text in the section, used as the source quote
    topic: str | None


def _plain(s: str) -> str:
    return _BOLD.sub(lambda m: m.group(1) or m.group(2), s).strip()


def _clean_body(s: str) -> str:
    s = " ".join(s.split())
    if s.startswith("(") and s.endswith(")") and s.count("(") == 1:
        s = s[1:-1].strip()
    return s


def _split_terms(term: str) -> list[str]:
    """'hard quota / soft quota' -> two terms; 'Read/Write' stays one."""
    parts = [p.strip() for p in re.split(r"\s+/\s+", term)]
    if len(parts) > 1 and all(p and len(p.split()) <= MAX_SPLIT_WORDS for p in parts):
        return parts
    return [term.strip()]


def parse_markdown(text: str) -> tuple[list[ExtractedPage], list[GlossaryEntry]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    sections: list[tuple[str | None, list[str]]] = []
    title: str | None = None
    lines: list[str] = []
    for raw in text.split("\n"):
        h = HEADING.match(raw)
        if h:
            level = len(h.group(1))
            if level == 1 and not sections and not lines:
                continue  # the document title ("# Terms")
            if title or any(l.strip() for l in lines):
                sections.append((title, lines))
            title, lines = _plain(h.group(2)), []
            continue
        lines.append(raw.rstrip())
    if title or any(l.strip() for l in lines):
        sections.append((title, lines))

    pages: list[ExtractedPage] = []
    entries: list[GlossaryEntry] = []
    for title, raw_lines in sections:
        page_no = len(pages) + 1
        rendered: list[str] = [title] if title else []
        # (term, inline definition, sub-bullet rendered lines, index of the term line in `rendered`)
        open_entry: dict | None = None

        def close(e: dict | None) -> None:
            if not e:
                return
            subs = [s for s in e["subs"] if not _SKIP_SUB.match(s)]
            if e["definition"]:
                body = _clean_body(e["definition"])
                quote = rendered[e["line"]].lstrip(" •")
            elif subs:
                body = "; ".join(_clean_body(s).rstrip(";.") for s in subs) + "."
                block = rendered[e["line"]: e["last"] + 1]
                quote = "\n".join(block).lstrip(" •")
            else:
                return
            if len(body) < 3:
                return
            for t in _split_terms(e["term"]):
                entries.append(GlossaryEntry(page_no, t, body, quote, title))

        for raw in raw_lines:
            if not raw.strip():
                continue
            b = BULLET.match(raw)
            if not b:
                rendered.append(_plain(raw))
                continue
            indent = len(b.group(1).replace("\t", "    "))
            content = b.group(2).strip()
            level = indent // 2 if indent < 4 else indent // 4
            if level == 0:
                close(open_entry)
                open_entry = None
                m = BOLD_TERM.match(content)
                line = "• " + _plain(content)
                rendered.append(line)
                if m:
                    open_entry = {"term": _plain(m.group(1)), "definition": (m.group(2) or "").strip(),
                                  "subs": [], "line": len(rendered) - 1, "last": len(rendered) - 1}
            else:
                rendered.append("  " * level + "• " + _plain(content))
                if open_entry is not None:
                    open_entry["subs"].append(_plain(content))
                    open_entry["last"] = len(rendered) - 1
        close(open_entry)
        pages.append(ExtractedPage(page_no=page_no, title=title, text="\n".join(rendered)))
    return pages, entries


def read_markdown(path) -> tuple[list[ExtractedPage], list[GlossaryEntry]]:
    with open(path, "rb") as f:
        data = f.read()
    return parse_markdown(data.decode("utf-8-sig", errors="replace"))
