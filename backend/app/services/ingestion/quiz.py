"""Answer-key quizzes -> questions exactly as written (BACKEND.md §5.2).

A PDF like
    1. What type of file system/s does not support NTFS permissions?
       A) NTFS
       B) ReFS
       **C) FAT32**
       **D) exFAT**
    True or False
    31. File auditing is enabled by default in Windows Server 2019.
        **False**
is read without the LLM: every numbered question keeps its wording, its choices and their order;
the bold choice(s) or the bold True/False line is the answer. Pages without such text (e.g. an image of
the answer key) add nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

QUIZ_MIN_QUESTIONS = 3

_QUESTION = re.compile(r"^(\d{1,3})[.)]\s*(.+)$")
_CHOICE = re.compile(r"^([A-Ha-h])[.)]\s+(.+)$")
_TF = re.compile(r"^(true|false)\.?$", re.IGNORECASE)
_INVISIBLE = re.compile(r"[​‌‍⁠﻿]")


@dataclass
class QuizEntry:
    page_no: int
    number: int
    question: str
    section: str | None
    type: str = "mcq"  # mcq | true_false
    choices: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    correct: list[int] = field(default_factory=list)  # mcq: indexes of the bold choices
    answer: str | None = None  # true_false: "true" | "false"
    seq: int = 0  # position in the quiz (numbers may restart between parts)

    def answer_key(self) -> dict:
        if self.type == "true_false":
            return {"type": "true_false", "number": self.number, "seq": self.seq, "answer": self.answer}
        return {"type": "mcq", "number": self.number, "seq": self.seq, "choices": self.choices,
                "labels": self.labels, "correct": self.correct}

    @property
    def complete(self) -> bool:
        if self.type == "true_false":
            return self.answer is not None
        return len(self.choices) >= 2 and bool(self.correct)


def answer_text(key: dict) -> str:
    """'C) FAT32; D) exFAT' or 'True' — the answer as the quiz writes it."""
    if key.get("type") == "true_false":
        return (key.get("answer") or "").capitalize()
    return "; ".join(f"{key['labels'][i]}) {key['choices'][i]}" for i in key.get("correct", []))


def _clean(s: str) -> str:
    return " ".join(_INVISIBLE.sub("", s).split())


def _lines(path: str | Path) -> list[tuple[int, str, bool, float]]:
    """(page_no, text, bold, left edge) for every text line, in reading order."""
    import pymupdf

    out = []
    with pymupdf.open(str(path)) as doc:
        for pno, page in enumerate(doc, start=1):
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    spans = [s for s in line["spans"] if _clean(s["text"])]
                    if not spans:
                        continue
                    text = _clean("".join(s["text"] for s in line["spans"]))
                    bold = all((s["flags"] & 16) or "bold" in s["font"].lower() for s in spans)
                    out.append((pno, text, bold, line["bbox"][0]))
    return out


def parse_quiz_lines(lines: list[tuple[int, str, bool, float]]) -> list[QuizEntry]:
    entries: list[QuizEntry] = []
    cur: QuizEntry | None = None
    section: str | None = None
    in_question = False  # still reading the question's wrapped lines
    left = 0.0  # where the question number starts; a wrapped choice is indented past it, a heading is not
    for pno, text, bold, x0 in lines:
        m = _QUESTION.match(text)
        if m and not _CHOICE.match(text):
            cur = QuizEntry(page_no=pno, number=int(m.group(1)), question=m.group(2).strip(), section=section)
            entries.append(cur)
            in_question = True
            left = x0
            continue
        indented = x0 > left + 2
        c = _CHOICE.match(text)
        if cur is not None and c and cur.type == "mcq" and cur.answer is None:
            label = c.group(1).upper()
            if not cur.labels or ord(label) == ord(cur.labels[-1]) + 1:
                cur.labels.append(label)
                cur.choices.append(c.group(2).strip())
                if bold:
                    cur.correct.append(len(cur.choices) - 1)
                in_question = False
                continue
        t = _TF.match(text)
        if cur is not None and t and not cur.choices and bold:
            cur.type = "true_false"
            cur.answer = t.group(1).lower()
            in_question = False
            continue
        if cur is not None and in_question and not bold:
            cur.question = f"{cur.question} {text}"  # the question wraps onto the next line
            continue
        if cur is not None and cur.choices and not in_question and indented:
            # a choice that wraps onto the next line (a bold right answer wraps in bold)
            if bold == (len(cur.choices) - 1 in cur.correct):
                cur.choices[-1] = f"{cur.choices[-1]} {text}"
                continue
        # Anything else is a heading ("True or False") for the questions that follow, or a page
        # header/footer. The current question stays open: its next choice letter still continues it.
        section = text.rstrip(":")
        in_question = False

    # A number may restart (Test I 1-20, Test II 1-10); the same question seen twice (a printed answer
    # key repeating the quiz) is kept once. A "question" with every choice bold is an outline, not a quiz.
    seen: set[tuple] = set()
    kept = []
    for e in entries:
        if not e.complete or (e.type == "mcq" and len(e.correct) == len(e.choices)):
            continue
        key = (" ".join(e.question.casefold().split()), tuple(c.casefold() for c in e.choices))
        if key in seen:
            continue
        seen.add(key)
        e.seq = len(kept) + 1
        kept.append(e)
    return kept


# Share of the file's text the questions must make up: a lesson with a few numbered, bolded lists (or a
# review quiz at the end) is still a lesson and goes through the normal extraction.
QUIZ_MIN_SHARE = 0.6


def _quiz_chars(e: QuizEntry) -> int:
    n = len(str(e.number)) + 2 + len(e.question) + sum(len(c) + 3 for c in e.choices)
    return n + (len(e.answer) if e.answer else 0)


def read_quiz_pdf(path: str | Path) -> list[QuizEntry]:
    """The quiz's questions, or [] when the file isn't an answer-key quiz."""
    lines = _lines(path)
    entries = parse_quiz_lines(lines)
    if len(entries) < QUIZ_MIN_QUESTIONS:
        return []
    total = sum(len(t) for _, t, _, _ in lines)
    if sum(_quiz_chars(e) for e in entries) < QUIZ_MIN_SHARE * total:
        return []
    return entries
