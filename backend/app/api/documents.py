"""File library (BACKEND.md §5, §12 Documents)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app import jobs
from app.api import get_document, get_reviewer
from app.config import settings
from app.db import get_db
from app.errors import AppError
from app.models import Document, Exam, Question, Reviewer, ReviewerDocument, SourceItem
from app.services import storage
from app.services.knowledge import EXTRACTION_VERSION, supersede_items, window_count

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED = {"pdf", "pptx", "ppt", "md", "txt"}


def file_type_of(filename: str) -> str:
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if ext not in ALLOWED:
        raise AppError(400, "UNSUPPORTED_FILE_TYPE", "Only PDF, PPTX, PPT, MD and TXT files can be used.", filename=filename)
    return ext


def document_summary(db: Session, doc: Document) -> dict:
    item_count = db.query(SourceItem).filter(SourceItem.document_id == doc.id, SourceItem.superseded_at.is_(None)).count()
    total_steps = (window_count(doc) + 1) if doc.page_count else None
    return {
        "id": doc.id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "status": doc.status,
        "busy": jobs.is_busy(doc),
        "page_count": doc.page_count,
        "page_unit": doc.page_unit,
        "size": doc.size,
        "item_count": item_count,
        "extraction_progress": doc.extraction_progress,
        "steps_done": doc.extraction_progress + (1 if doc.page_count else 0),
        "steps_total": total_steps,
        "error_code": doc.error_code,
        "error_message": doc.error_message,
        "reviewer_ids": [l.reviewer_id for l in doc.reviewer_links],
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


def document_detail(db: Session, doc: Document) -> dict:
    out = document_summary(db, doc)
    kinds = {"definition": 0, "fact": 0}
    for it in db.query(SourceItem).filter(SourceItem.document_id == doc.id, SourceItem.superseded_at.is_(None)):
        kinds[it.kind] = kinds.get(it.kind, 0) + 1
    out.update({
        "items_by_kind": kinds,
        "extraction_version": doc.extraction_version,
        "outdated": doc.status == "ready" and doc.extraction_version < EXTRACTION_VERSION,
        "copied_from_document_id": doc.copied_from_document_id,
    })
    return out


def link(db: Session, reviewer: Reviewer, doc: Document) -> None:
    if any(l.document_id == doc.id for l in reviewer.links):
        return
    db.add(ReviewerDocument(reviewer_id=reviewer.id, document_id=doc.id, position=len(reviewer.links)))
    db.flush()
    db.refresh(reviewer)


def find_duplicate(db: Session, sha256: str) -> Document | None:
    return db.query(Document).filter(Document.sha256 == sha256, Document.owner_id.is_(None)).first()


def reuse_duplicate(db: Session, existing: Document, reviewer: Reviewer | None) -> JSONResponse:
    """Same bytes already in the library: link it, and re-run a failed one (§5.5)."""
    if reviewer is not None:
        link(db, reviewer, existing)
    if existing.status == "failed":
        existing.extraction_progress = 0
        existing.status = "uploaded"
        existing.error_code = existing.error_message = None
        if not storage.has_file(db, existing) and not existing.page_count:
            existing.error_code = "FILE_MISSING"
    db.commit()
    code = 202 if existing.status == "uploaded" else 200
    return JSONResponse(status_code=code, content={**document_summary(db, existing), "duplicate": True})


def create_document(db: Session, filename: str, file_type: str, data: bytes, sha256: str,
                    reviewer: Reviewer | None) -> Document:
    doc = Document(filename=Path(filename).name, file_type=file_type, storage_path="", sha256=sha256,
                   status="uploaded", extraction_version=EXTRACTION_VERSION, size=len(data))
    db.add(doc)
    db.flush()
    storage.save_file(db, doc, data)
    if reviewer is not None:
        link(db, reviewer, doc)
    db.commit()
    return doc


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    reviewer_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """Single-request upload (fine on localhost). The browser uses the chunked /uploads route instead."""
    file_type = file_type_of(file.filename or "")
    reviewer = get_reviewer(db, reviewer_id) if reviewer_id else None
    data = bytearray()
    while True:
        chunk = await file.read(1 << 20)
        if not chunk:
            break
        data += chunk
        if len(data) > settings.max_upload_bytes:
            raise AppError(413, "FILE_TOO_LARGE", f"This file is over {settings.max_upload_mb} MB.")
    data = bytes(data)
    if not data or not storage.looks_like(file_type, data):
        raise AppError(400, "UNSUPPORTED_FILE_TYPE", f"This file does not look like a {file_type.upper()} file.",
                       filename=file.filename)
    digest = storage.sha256_bytes(data)
    existing = find_duplicate(db, digest)
    if existing is not None:
        return reuse_duplicate(db, existing, reviewer)
    doc = create_document(db, file.filename or f"upload.{file_type}", file_type, data, digest, reviewer)
    return JSONResponse(status_code=202, content={**document_summary(db, doc), "duplicate": False})


@router.get("")
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(Document).order_by(Document.created_at.desc()).all()
    return [document_summary(db, d) for d in docs]


@router.get("/{document_id}")
def get_document_detail(document_id: str, db: Session = Depends(get_db)):
    return document_detail(db, get_document(db, document_id))


@router.post("/{document_id}/process")
def process_document(document_id: str, db: Session = Depends(get_db)):
    """Run one processing step (read pages, or one Gemini window). Call until status is ready/failed."""
    doc = get_document(db, document_id)
    doc = jobs.document_step(db, doc)
    db.refresh(doc)
    return {**document_detail(db, doc), "done": doc.status in ("ready", "failed")}


@router.post("/{document_id}/reprocess", status_code=202)
def reprocess_document(document_id: str, db: Session = Depends(get_db)):
    """Start over (ready/failed doc), or continue a quota-stopped one. Then call /process."""
    doc = get_document(db, document_id)
    if jobs.is_busy(doc):
        raise AppError(409, "ALREADY_PROCESSING", "This file is being processed right now.")
    resume = doc.status == "failed" and doc.error_code in ("LLM_QUOTA_EXCEEDED", "LLM_ERROR") and doc.extraction_progress > 0
    if not resume:
        supersede_items(db, doc)
        doc.extraction_progress = 0
        doc.copied_from_document_id = None
    if not doc.page_count and not storage.has_file(db, doc):
        raise AppError(409, "FILE_MISSING", "The uploaded file is no longer stored. Upload it again.")
    doc.status = "uploaded" if not doc.page_count else "extracting"
    doc.error_code = doc.error_message = None
    db.commit()
    return {**document_summary(db, doc), "resumed": resume}


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, force: bool = False, db: Session = Depends(get_db)):
    doc = get_document(db, document_id)
    links = list(doc.reviewer_links)
    if links and not force:
        raise AppError(409, "DOCUMENT_IN_USE", "This file is part of a reviewer. Remove it there first, or force.",
                       reviewer_ids=[l.reviewer_id for l in links],
                       reviewers=[{"id": l.reviewer.id, "title": l.reviewer.title} for l in links])
    if links:
        item_ids = [r[0] for r in db.query(SourceItem.id).filter(SourceItem.document_id == doc.id)]
        if item_ids:
            exam_ids = {r[0] for r in db.query(Question.exam_id).filter(Question.source_item_id.in_(item_ids)).distinct()}
            for eid in exam_ids:
                exam = db.get(Exam, eid)
                if exam is not None:
                    db.delete(exam)
        db.flush()  # the reviewer links go with the document (cascade)
    db.delete(doc)
    db.commit()
    return Response(status_code=204)
