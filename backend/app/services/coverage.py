"""Which items of a reviewer have already been part of an exam (BACKEND.md §4, "used items")."""

from __future__ import annotations

from sqlalchemy import select
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


def used_item_ids(db: Session, reviewer: Reviewer) -> set[str]:
    stmt = (
        select(Question.source_item_id)
        .join(Exam, Exam.id == Question.exam_id)
        .where(
            Exam.reviewer_id == reviewer.id,
            Exam.coverage_epoch == reviewer.coverage_epoch,
            Exam.status == "ready",
            Exam.all_items.is_(False),  # an "All items" set is a full review, not part of coverage
        )
        .distinct()
    )
    return {r[0] for r in db.execute(stmt)}


def doc_item_counts(db: Session, reviewer: Reviewer) -> dict[str, dict[str, int]]:
    used = used_item_ids(db, reviewer)
    out: dict[str, dict[str, int]] = {}
    for it in active_items(db, reviewer):
        d = out.setdefault(it.document_id, {"items": 0, "used": 0})
        d["items"] += 1
        if it.id in used:
            d["used"] += 1
    return out
