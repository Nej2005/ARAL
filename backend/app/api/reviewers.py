"""Reviewers: combining files, outline, scope, availability, coverage, export (§7, §11, §12)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api import get_document, get_reviewer
from app.db import get_db
from app.errors import AppError
from app.models import Document, DocumentPage, Exam, Question, Reviewer, ReviewerDocument, SourceItem
from app.schemas import AddDocument, AvailabilityRequest, CreateReviewer, ExportRequest, PatchReviewer
from app.services.attempts import exam_scores
from app.services.coverage import active_items, doc_item_counts, used_item_ids
from app.services.export.anki_csv import items_csv
from app.services.export.pdf_study_sheet import study_sheet_pdf
from app.services.generation.selector import availability as compute_availability
from app.services.scope import filter_items, validate_scope

router = APIRouter(prefix="/reviewers", tags=["reviewers"])


def slug(s: str) -> str:
    s = re.sub(r"[^\w]+", "-", s.strip().casefold()).strip("-")
    return s or "reviewer"


def reviewer_status(reviewer: Reviewer) -> str:
    statuses = [d.status for d in reviewer.documents]
    if any(s == "failed" for s in statuses):
        return "needs_attention"
    if any(s != "ready" for s in statuses):
        return "processing"
    return "ready"


def reviewer_summary(db: Session, r: Reviewer) -> dict:
    counts = doc_item_counts(db, r)
    items = sum(c["items"] for c in counts.values())
    used = sum(c["used"] for c in counts.values())
    completed = [a for e in r.exams for a in e.attempts if a.status == "completed" and a.kind == "full"]
    latest = max(completed, key=lambda a: a.completed_at, default=None)
    return {
        "id": r.id,
        "title": r.title,
        "document_count": len(r.links),
        "item_count": items,
        "used_items": used,
        "unused_items": items - used,
        "status": reviewer_status(r),
        "exam_count": len(r.exams),
        "last_score": {"correct_count": latest.correct_count, "total": latest.total} if latest else None,
        "coverage_epoch": r.coverage_epoch,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def reviewer_detail(db: Session, r: Reviewer) -> dict:
    out = reviewer_summary(db, r)
    counts = doc_item_counts(db, r)
    from app import jobs
    from app.services.knowledge import window_count

    out["documents"] = [
        {
            "id": d.id,
            "filename": d.filename,
            "file_type": d.file_type,
            "status": d.status,
            "busy": jobs.is_busy(d),
            "error_code": d.error_code,
            "page_count": d.page_count,
            "page_unit": d.page_unit,
            "steps_done": d.extraction_progress + (1 if d.page_count else 0),
            "steps_total": (window_count(d) + 1) if d.page_count else None,
            "item_count": counts.get(d.id, {}).get("items", 0),
            "used_items": counts.get(d.id, {}).get("used", 0),
            "exam_count": len(exams_using_document(db, d.id, r.id)),
            "shared": len(d.reviewer_links) > 1,
        }
        for d in r.documents
    ]
    return out


@router.post("", status_code=201)
def create_reviewer(body: CreateReviewer, db: Session = Depends(get_db)):
    r = Reviewer(title=body.title)
    db.add(r)
    db.flush()
    seen = set()
    for pos, did in enumerate(body.document_ids):
        if did in seen:
            continue
        seen.add(did)
        doc = get_document(db, did)
        db.add(ReviewerDocument(reviewer_id=r.id, document_id=doc.id, position=pos))
    db.commit()
    db.refresh(r)
    return reviewer_detail(db, r)


@router.get("")
def list_reviewers(db: Session = Depends(get_db)):
    rs = db.query(Reviewer).order_by(Reviewer.updated_at.desc()).all()
    return [reviewer_summary(db, r) for r in rs]


@router.get("/{reviewer_id}")
def get_reviewer_detail(reviewer_id: str, db: Session = Depends(get_db)):
    return reviewer_detail(db, get_reviewer(db, reviewer_id))


@router.patch("/{reviewer_id}")
def patch_reviewer(reviewer_id: str, body: PatchReviewer, db: Session = Depends(get_db)):
    r = get_reviewer(db, reviewer_id)
    if body.title is not None:
        r.title = body.title.strip()
    if body.document_order is not None:
        current = {l.document_id: l for l in r.links}
        if set(body.document_order) != set(current):
            raise AppError(422, "VALIDATION_ERROR", "document_order must list every document of the reviewer exactly once.")
        for pos, did in enumerate(body.document_order):
            current[did].position = pos
    db.commit()
    db.refresh(r)
    return reviewer_detail(db, r)


@router.delete("/{reviewer_id}", status_code=204)
def delete_reviewer(reviewer_id: str, db: Session = Depends(get_db)):
    r = get_reviewer(db, reviewer_id)
    db.delete(r)
    db.commit()
    return Response(status_code=204)


@router.post("/{reviewer_id}/documents")
def add_document(reviewer_id: str, body: AddDocument, db: Session = Depends(get_db)):
    r = get_reviewer(db, reviewer_id)
    doc = get_document(db, body.document_id)
    if not any(l.document_id == doc.id for l in r.links):
        db.add(ReviewerDocument(reviewer_id=r.id, document_id=doc.id, position=len(r.links)))
        db.commit()
        db.refresh(r)
    return reviewer_detail(db, r)


@router.delete("/{reviewer_id}/documents/{document_id}")
def remove_document(reviewer_id: str, document_id: str, delete_file: bool = False, db: Session = Depends(get_db)):
    """Remove a file from the reviewer.

    With `delete_file=true` and no other reviewer using it, the file itself is deleted too, along with
    the exams that have questions from it (their questions would otherwise point at nothing).
    """
    r = get_reviewer(db, reviewer_id)
    link = next((l for l in r.links if l.document_id == document_id), None)
    if link is None:
        raise AppError(404, "NOT_FOUND", "That file is not part of this reviewer.")
    if len(r.links) == 1:
        raise AppError(409, "EMPTY_REVIEWER", "A reviewer needs at least one file. Delete the reviewer instead.")
    doc = link.document
    other_users = [l for l in doc.reviewer_links if l.reviewer_id != r.id]
    deleted_exams = 0
    deleted_file = False
    if delete_file and not other_users:
        for exam_id in exams_using_document(db, doc.id):
            exam = db.get(Exam, exam_id)
            if exam is not None:
                db.delete(exam)
                deleted_exams += 1
        db.flush()
        db.delete(doc)  # pages, items and the reviewer link go with it
        deleted_file = True
    else:
        db.delete(link)
    db.commit()
    db.refresh(r)
    return {**reviewer_detail(db, r), "deleted_file": deleted_file, "deleted_exams": deleted_exams}


def exams_using_document(db: Session, document_id: str, reviewer_id: str | None = None) -> set[str]:
    q = (db.query(Question.exam_id)
         .join(SourceItem, SourceItem.id == Question.source_item_id)
         .filter(SourceItem.document_id == document_id))
    if reviewer_id:
        q = q.join(Exam, Exam.id == Question.exam_id).filter(Exam.reviewer_id == reviewer_id)
    return {row[0] for row in q.distinct()}


def _topics(items: list[SourceItem], used: set[str]) -> list[dict]:
    topics: dict[str, dict] = {}
    for it in items:
        if not it.topic_key:
            continue
        t = topics.setdefault(it.topic_key, {"topic": it.topic, "topic_key": it.topic_key, "item_count": 0, "unused_count": 0})
        t["item_count"] += 1
        if it.id not in used:
            t["unused_count"] += 1
    return sorted(topics.values(), key=lambda t: t["topic"].casefold())


@router.get("/{reviewer_id}/outline")
def outline(reviewer_id: str, db: Session = Depends(get_db)):
    r = get_reviewer(db, reviewer_id)
    items = active_items(db, r)
    used = used_item_ids(db, r)
    per_page: dict[tuple[str, int], int] = {}
    for it in items:
        per_page[(it.document_id, it.page_no)] = per_page.get((it.document_id, it.page_no), 0) + 1
    docs = []
    for d in r.documents:
        pages = db.query(DocumentPage).filter(DocumentPage.document_id == d.id).order_by(DocumentPage.page_no).all()
        docs.append({
            "document_id": d.id,
            "filename": d.filename,
            "status": d.status,
            "page_count": d.page_count,
            "page_unit": d.page_unit,
            "pages": [{"page_no": p.page_no, "title": p.title, "item_count": per_page.get((d.id, p.page_no), 0)}
                      for p in pages],
        })
    return {"documents": docs, "topics": _topics(items, used)}


def _resolve_scope(db: Session, r: Reviewer, scope) -> dict | None:
    items = active_items(db, r)
    keys = {i.topic_key for i in items if i.topic_key}
    return validate_scope(scope.model_dump() if scope is not None else None, r.documents, keys)


@router.post("/{reviewer_id}/availability")
def availability(reviewer_id: str, body: AvailabilityRequest, db: Session = Depends(get_db)):
    r = get_reviewer(db, reviewer_id)
    scope = _resolve_scope(db, r, body.scope)
    items = active_items(db, r)
    used = used_item_ids(db, r)
    scoped = filter_items(items, scope)
    av = compute_availability(scoped, items, used, list(body.types))
    in_scope = sum(1 for i in scoped if set(body.types) != {"identification"} or i.kind == "definition")
    return {
        "total_items": av.total_items,
        "used_items": av.used_items,
        "unused_items": av.unused_items,
        "max_count_for_types": av.max_count_for_types,
        "unused_by_type": av.unused_by_type,
        "unused_outside_scope": av.unused_outside_scope,
        "all_items_count": in_scope if body.types else 0,  # for "All items": reviewed ones count too
        "scope": scope,
    }


@router.post("/{reviewer_id}/coverage/reset")
def reset_coverage(reviewer_id: str, db: Session = Depends(get_db)):
    r = get_reviewer(db, reviewer_id)
    r.coverage_epoch += 1
    db.commit()
    return {"coverage_epoch": r.coverage_epoch}


@router.post("/{reviewer_id}/export")
def export_reviewer(reviewer_id: str, body: ExportRequest, db: Session = Depends(get_db)):
    r = get_reviewer(db, reviewer_id)
    scope = _resolve_scope(db, r, body.scope)
    items = filter_items(active_items(db, r), scope)
    docs = {d.id: d for d in r.documents}
    base = slug(r.title)
    if body.format == "pdf":
        data = study_sheet_pdf(r, items, docs)
        return Response(content=bytes(data), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{base}-study-sheet.pdf"'})
    data = items_csv(r, items, docs)
    return Response(content=data.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{base}-anki.csv"'})


# Exams of a reviewer live in exams.py but are listed here for a tidy URL.
@router.get("/{reviewer_id}/exams")
def list_exams(reviewer_id: str, db: Session = Depends(get_db)):
    from app.api.exams import exam_payload

    r = get_reviewer(db, reviewer_id)
    exams = sorted(r.exams, key=lambda e: e.created_at, reverse=True)
    return [{**exam_payload(e), **exam_scores(e)} for e in exams]
