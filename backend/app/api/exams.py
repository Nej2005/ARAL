"""Exams: create, poll, next set, export (BACKEND.md §8, §10.3, §11.1, §12)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app import jobs
from app.api import get_exam, get_reviewer
from app.api.reviewers import _resolve_scope, slug
from app.config import settings
from app.db import get_db
from app.errors import AppError
from app.models import Exam, Reviewer
from app.schemas import CreateExam, NextSet
from app.services.attempts import exam_scores
from app.services.coverage import active_items, used_item_ids
from app.services.export.anki_csv import exam_csv
from app.services.export.pdf_exam import exam_pdf
from app.services.scope import filter_items

router = APIRouter(tags=["exams"])


def exam_payload(e: Exam) -> dict:
    return {
        "id": e.id,
        "reviewer_id": e.reviewer_id,
        "status": e.status,
        "types": e.question_types,
        "scope": e.scope,
        "requested_count": e.requested_count,
        "actual_count": e.actual_count,
        "shortfall": e.shortfall,
        "parent_exam_id": e.parent_exam_id,
        "error_code": e.error_code,
        "error_message": e.error_message,
        "busy": jobs.is_busy(e),
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _check_ready(r: Reviewer) -> None:
    not_ready = [{"id": d.id, "filename": d.filename, "status": d.status} for d in r.documents if d.status != "ready"]
    if not_ready:
        raise AppError(409, "DOCUMENTS_NOT_READY", "A file in this reviewer is still processing or failed.",
                       documents=not_ready)
    if not r.documents:
        raise AppError(409, "EMPTY_REVIEWER", "Add a file to this reviewer first.")


def _start(db: Session, r: Reviewer, types: list[str], count: int, scope,
           parent: Exam | None = None) -> JSONResponse:
    _check_ready(r)
    if count > settings.max_exam_items:
        raise AppError(422, "VALIDATION_ERROR", f"count must be between 1 and {settings.max_exam_items}.")
    items = active_items(db, r)
    used = used_item_ids(db, r)
    unused_scoped = [i for i in filter_items(items, scope) if i.id not in used]
    if not unused_scoped:
        outside = sum(1 for i in items if i.id not in used)
        raise AppError(409, "ALL_ITEMS_REVIEWED",
                       "Every item in this reviewer has been part of an exam." if not outside
                       else "Every item in the selected part has been part of an exam.",
                       unused_outside_scope=outside)
    if set(types) == {"identification"} and not any(i.kind == "definition" for i in unused_scoped):
        raise AppError(409, "ALL_ITEMS_REVIEWED", "No unused definitions are left for Identification.",
                       unused_outside_scope=0)
    exam = Exam(reviewer_id=r.id, question_types=list(types), requested_count=count, scope=scope,
                coverage_epoch=r.coverage_epoch, parent_exam_id=parent.id if parent else None, status="generating")
    db.add(exam)
    db.commit()
    return JSONResponse(status_code=202, content=exam_payload(exam))


@router.post("/reviewers/{reviewer_id}/exams")
def create_exam(reviewer_id: str, body: CreateExam, db: Session = Depends(get_db)):
    r = get_reviewer(db, reviewer_id)
    scope = _resolve_scope(db, r, body.scope)
    return _start(db, r, body.types, body.count, scope)


@router.post("/exams/{exam_id}/process")
def process_exam(exam_id: str, db: Session = Depends(get_db)):
    """Build the exam's questions (1-2 Gemini calls). Call until status is ready/failed."""
    e = get_exam(db, exam_id)
    e = jobs.exam_step(db, e)
    db.refresh(e)
    return {**exam_payload(e), **exam_scores(e), "done": e.status in ("ready", "failed")}


@router.delete("/exams/{exam_id}", status_code=204)
def delete_exam(exam_id: str, db: Session = Depends(get_db)):
    """Delete an exam set with its questions, attempts and answers. Its items count as new again."""
    e = get_exam(db, exam_id)
    if jobs.is_busy(e):
        raise AppError(409, "ALREADY_PROCESSING", "This exam is being built right now. Try again in a moment.")
    db.delete(e)
    db.commit()
    return Response(status_code=204)


@router.get("/exams/{exam_id}")
def get_exam_status(exam_id: str, db: Session = Depends(get_db)):
    e = get_exam(db, exam_id)
    return {**exam_payload(e), **exam_scores(e)}


@router.post("/exams/{exam_id}/next-set")
def next_set(exam_id: str, body: NextSet | None = None, db: Session = Depends(get_db)):
    parent = get_exam(db, exam_id)
    r = parent.reviewer
    body = body or NextSet()
    types = body.types or list(parent.question_types)
    count = body.count or parent.requested_count
    if "scope" in body.model_fields_set:
        scope = _resolve_scope(db, r, body.scope)  # explicit null = whole reviewer
    else:
        scope = parent.scope
    return _start(db, r, types, count, scope, parent=parent)


@router.get("/exams/{exam_id}/export")
def export_exam(exam_id: str, format: str = Query(default="pdf"), answer_key: str = Query(default="end"),
                db: Session = Depends(get_db)):
    e = get_exam(db, exam_id)
    if e.status != "ready":
        raise AppError(409, "EXAM_NOT_READY", "This exam is not ready yet.")
    docs = {d.id: d for d in e.reviewer.documents}
    base = f"{slug(e.reviewer.title)}-exam-{_set_number(e)}"
    if format == "csv":
        data = exam_csv(e, docs)
        return Response(content=data.encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{base}.csv"'})
    if format != "pdf":
        raise AppError(422, "VALIDATION_ERROR", "format must be pdf or csv.")
    data = exam_pdf(e, docs, with_answer_key=(answer_key != "none"))
    return Response(content=bytes(data), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{base}.pdf"'})


def _set_number(e: Exam) -> int:
    exams = sorted(e.reviewer.exams, key=lambda x: x.created_at)
    return next((i for i, x in enumerate(exams, start=1) if x.id == e.id), 1)
