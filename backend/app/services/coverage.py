"""Which items of a reviewer have already been part of an exam (BACKEND.md §4, "used items")."""

from __future__ import annotations

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import Exam, Question, Reviewer, SourceItem


def active_items(db: Session, reviewer: Reviewer) -> list[SourceItem]:
    """Non-superseded items of every document in the reviewer, in file order."""
    out: list[SourceItem] = []
    for link in reviewer.links:
        rows = (
            db.query(SourceItem)
            .filter(SourceItem.document_id == link.document_id, SourceItem.superseded_at.is_(None))
            .order_by(SourceItem.page_no, SourceItem.quote_start)
            .all()
        )
        out.extend(rows)
    return out


def _counted_exams(reviewer: Reviewer) -> tuple:
    """The exams whose questions count as "used": ready sets of this reviewer since the last coverage reset."""
    return (
        Exam.reviewer_id == reviewer.id,
        Exam.coverage_epoch == reviewer.coverage_epoch,
        Exam.status == "ready",
        Exam.all_items.is_(False),  # an "All items" set is a full review, not part of coverage
    )


def used_item_ids(db: Session, reviewer: Reviewer) -> set[str]:
    stmt = (
        select(Question.source_item_id)
        .join(Exam, Exam.id == Question.exam_id)
        .where(*_counted_exams(reviewer))
        .distinct()
    )
    return {r[0] for r in db.execute(stmt)}


def doc_item_counts(db: Session, reviewer: Reviewer) -> dict[str, dict[str, int]]:
    """{document id: {"items": active items, "used": those already in a counted exam}}, for documents with items.

    Counted in the database (two GROUP BY queries) rather than by loading every item."""
    doc_ids = [link.document_id for link in reviewer.links]
    if not doc_ids:
        return {}
    active = (SourceItem.document_id.in_(doc_ids), SourceItem.superseded_at.is_(None))
    out = {doc: {"items": n, "used": 0} for doc, n in db.execute(
        select(SourceItem.document_id, func.count()).where(*active).group_by(SourceItem.document_id))}
    used = (
        select(SourceItem.document_id, func.count(distinct(SourceItem.id)))
        .join(Question, Question.source_item_id == SourceItem.id)
        .join(Exam, Exam.id == Question.exam_id)
        .where(*active, *_counted_exams(reviewer))
        .group_by(SourceItem.document_id)
    )
    for doc, n in db.execute(used):
        out.setdefault(doc, {"items": 0, "used": 0})["used"] = n
    return out
