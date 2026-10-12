"""Link an answer-key quiz to the lesson it comes from, so every answer cites the lesson (BACKEND.md §5.2).

A quiz says *what* the answer is, not *why*. When the quiz comes from a lesson, every question can point at
the lesson's own words: the bullets of the lesson PDF are ranked by the words they share with the question and
its answer, and the best one is shown as the source. Text is quoted as the PDF shows it; only characters a
broken font maps wrongly are repaired (see `repair_text`).

    # 1. suggest: the 3 best lesson passages for every quiz question, to review by hand
    .venv\Scripts\python samples\link_quiz_lesson.py suggest LESSON.pdf QUIZ.pdf

    # 2. apply a reviewed map (JSON: {question text (casefolded): {filename, page_no, location, passages, disagrees}})
    #    to the quiz's items and to every question built from them; DATABASE_URL picks the database
    .venv\Scripts\python samples\link_quiz_lesson.py apply MAP.json QUIZ_DOCUMENT_ID
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# Private-use ligature glyphs some fonts emit instead of "fi"/"fl" (the slide shows "Configuring", the text
# layer says "Con\uf001guring" or drops the glyph).
_LIGATURES = {"\uf001": "fi", "\uf002": "fl", "\ufb01": "fi", "\ufb02": "fl"}
# Letters a broken font maps to the wrong code point; the slide shows the plain letter or digit.
_ALVEOLAR_CLICK = re.compile(r"ǂ")           # "Leǂrning" -> "Learning", "ǂnd" -> "and"
_A_CARON_DIGIT = re.compile(r"(?<=\d)Ǎ(?=\d)")  # "20Ǎ9" -> "2019"


def repair_text(s: str) -> str:
    for k, v in _LIGATURES.items():
        s = s.replace(k, v)
    s = _ALVEOLAR_CLICK.sub("a", s)
    return _A_CARON_DIGIT.sub("1", s)


@dataclass
class Passage:
    page_no: int
    text: str


_BULLET = re.compile(r"^\s*[•\-–—▪◦●]\s*")


_STOP = set("""a an the and or of to in on for with by as at from into than that this these those its it is are be
can may will not no all any each other such which who what when where how your their you they them do does
following true false""".split())


def _words(s: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", s.lower()):
        if len(w) < 3 or w in _STOP:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if w.endswith(suf) and len(w) - len(suf) >= 4:
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


def rank_passages(query: str, passages: list[Passage], top: int = 3) -> list[tuple[float, Passage]]:
    """Passages that share the most (rare) words with `query`, best first."""
    df = Counter(w for p in passages for w in set(_words(p.text)))
    n = len(passages)
    q = set(_words(query))
    scored = []
    for p in passages:
        pw = set(_words(p.text))
        score = sum(math.log(1 + n / df[w]) for w in q & pw)
        scored.append((score / (1 + 0.02 * len(pw)), p))
    scored.sort(key=lambda x: -x[0])
    return scored[:top]


def read_lesson_pdf(path: str | Path) -> list[Passage]:
    """Passages read block by block, so two-column slides don't interleave their columns."""
    import pymupdf

    out: list[Passage] = []
    with pymupdf.open(str(path)) as doc:
        for pno, page in enumerate(doc, start=1):
            blocks = [" ".join(repair_text(b[4]).split()) for b in page.get_text("blocks") if b[4].strip()]
            cur: list[str] = []
            for i, t in enumerate(blocks):
                if i == 0:  # the slide title
                    continue
                if _BULLET.match(t):
                    if cur:
                        out.append(Passage(pno, " ".join(cur)))
                    cur = [_BULLET.sub("", t).strip()]
                else:
                    cur.append(t)  # the bullet wraps into the next block
            if cur:
                out.append(Passage(pno, " ".join(cur)))
    return [p for p in out if len(p.text.split()) >= 3]


def suggest(lesson_pdf: str, quiz_pdf: str) -> None:
    from app.services.ingestion.quiz import answer_text, read_quiz_pdf

    passages = read_lesson_pdf(lesson_pdf)
    for e in read_quiz_pdf(quiz_pdf):
        query = " ".join([e.question, *(e.choices[i] for i in e.correct)])
        print(f"\n#{e.number} {e.question}  => {answer_text(e.answer_key())}")
        for score, p in rank_passages(query, passages):
            print(f"   [{score:4.1f}] p{p.page_no}: {p.text[:220]}")


def apply(map_json: str, quiz_document_id: str) -> None:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Question, SourceItem

    links = json.load(open(map_json, encoding="utf-8"))
    with SessionLocal() as db:
        items = db.scalars(select(SourceItem).where(SourceItem.document_id == quiz_document_id,
                                                    SourceItem.superseded_at.is_(None))).all()
        done = 0
        for it in items:
            lesson = links.get(" ".join(it.body.split()).casefold())
            if not lesson or not it.answer_key:
                print("no lesson passage for:", it.body[:80])
                continue
            it.answer_key = {**it.answer_key, "lesson": lesson}
            for q in db.scalars(select(Question).where(Question.source_item_id == it.id)):
                q.explanation = {**(q.explanation or {}), "lesson": lesson}
            done += 1
        db.commit()
    print(f"linked {done}/{len(items)} questions")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    {"suggest": suggest, "apply": apply}[sys.argv[1]](*sys.argv[2:])
