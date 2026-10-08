"""File library (BACKEND.md §5, §12 Documents)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app import jobs
from app.api import get_document, get_reviewer
from app.config import settings
from app.db import get_db
from app.errors import AppError
from app.models import Document, Exam, Question, Reviewer, ReviewerDocument, SourceItem
from app.services.ingestion.dedupe import sha256_stream
from app.services.knowledge import EXTRACTION_VERSION

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED = {"pdf", "pptx", "ppt"}
MAGIC = {"pdf": (b"%PDF",), "pptx": (b"PK\x03\x04",), "ppt": (b"\xd0\xcf\x11\xe0",)}


def _file_type(filename: str) -> str:
    ext = Path(filename or "").suffix.lower().lstrip(".")
    if ext not in ALLOWED:
        raise AppError(400, "UNSUPPORTED_FILE_TYPE", "Only PDF, PPTX and PPT files can be used.", filename=filename)
    return ext


def document_summary(db: Session, doc: Document) -> dict:
    item_count = db.query(SourceItem).filter(SourceItem.document_id == doc.id, SourceItem.superseded_at.is_(None)).count()
    return {
        "id": doc.id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "status": doc.status,
        "page_count": doc.page_count,
        "page_unit": doc.page_unit,
        "item_count": item_count,
        "reviewer_ids": [l.reviewer_id for l in doc.reviewer_links],
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


def document_detail(db: Session, doc: Document) -> dict:
    out = document_summary(db, doc)
    kinds = {"definition": 0, "fact": 0}
    for it in db.query(SourceItem).filter(SourceItem.document_id == doc.id, SourceItem.superseded_at.is_(None)):
        kinds[it.kind] = kinds.get(it.kind, 0) + 1
    out.update({
        "error_code": doc.error_code,
        "error_message": doc.error_message,
        "items_by_kind": kinds,
        "extraction_version": doc.extraction_version,
        "extraction_progress": doc.extraction_progress,
        "outdated": doc.status == "ready" and doc.extraction_version < EXTRACTION_VERSION,
        "copied_from_document_id": doc.copied_from_document_id,
    })
    return out


def _link(db: Session, reviewer: Reviewer, doc: Document) -> None:
    if any(l.document_id == doc.id for l in reviewer.links):
        return
    db.add(ReviewerDocument(reviewer_id=reviewer.id, document_id=doc.id, position=len(reviewer.links)))
    db.flush()
    db.refresh(reviewer)


@router.post("")
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    reviewer_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    file_type = _file_type(file.filename or "")
    reviewer = get_reviewer(db, reviewer_id) if reviewer_id else None

    # Stream to a temp file, hashing as we go, and enforce the size limit.
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_type}")
    size = 0
    head = b""
    try:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            if not head:
                head = chunk[:8]
            size += len(chunk)
            if size > settings.max_upload_bytes:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                raise AppError(413, "FILE_TOO_LARGE", f"This file is over {settings.max_upload_mb} MB.")
            tmp.write(chunk)
        tmp.close()
        if size == 0 or not any(head.startswith(m) for m in MAGIC[file_type]):
            Path(tmp.name).unlink(missing_ok=True)
            raise AppError(400, "UNSUPPORTED_FILE_TYPE",
                           f"This file does not look like a {file_type.upper()} file.", filename=file.filename)
        with open(tmp.name, "rb") as f:
            digest = sha256_stream(f)
    finally:
        if not tmp.closed:
            tmp.close()

    existing = db.query(Document).filter(Document.sha256 == digest, Document.owner_id.is_(None)).first()
    if existing is not None:
        Path(tmp.name).unlink(missing_ok=True)
        if reviewer is not None:
            _link(db, reviewer, existing)
            db.commit()
        if existing.status == "failed":
            existing.extraction_progress = 0
            existing.status = "uploaded"
            db.commit()
            background.add_task(jobs.extract_document, existing.id)
            return JSONResponse(status_code=202, content={**document_summary(db, existing), "duplicate": True})
        return JSONResponse(status_code=200, content={**document_summary(db, existing), "duplicate": True})

    doc = Document(filename=Path(file.filename).name, file_type=file_type, storage_path="", sha256=digest,
                   status="uploaded", extraction_version=EXTRACTION_VERSION)
    db.add(doc)
    db.flush()
    dest_dir = settings.resolved_storage_dir() / doc.id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"original.{file_type}"
    shutil.move(tmp.name, dest)
    doc.storage_path = str(dest)
    if reviewer is not None:
        _link(db, reviewer, doc)
    db.commit()
    background.add_task(jobs.extract_document, doc.id)
    return JSONResponse(status_code=202, content={**document_summary(db, doc), "duplicate": False})


@router.get("")
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(Document).order_by(Document.created_at.desc()).all()
    return [document_summary(db, d) for d in docs]


@router.get("/{document_id}")
def get_document_detail(document_id: str, db: Session = Depends(get_db)):
    return document_detail(db, get_document(db, document_id))


@router.post("/{document_id}/reprocess", status_code=202)
def reprocess_document(document_id: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    doc = get_document(db, document_id)
    if doc.status == "extracting":
        raise AppError(409, "ALREADY_PROCESSING", "This file is being processed right now.")
    from app.services.knowledge import supersede_items

    # A quota stop or an interrupted job keeps its progress; reprocessing a ready/failed doc starts over.
    resume = (doc.status == "failed" and doc.error_code in ("LLM_QUOTA_EXCEEDED", "INTERRUPTED")
              and doc.extraction_progress > 0)
    if not resume:
        supersede_items(db, doc)
        doc.extraction_progress = 0
        doc.copied_from_document_id = None
    doc.status = "uploaded"
    doc.error_code = doc.error_message = None
    db.commit()
    background.add_task(jobs.extract_document, doc.id)
    return {"id": doc.id, "status": "extracting", "resumed": resume}


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, force: bool = False, db: Session = Depends(get_db)):
    doc = get_document(db, document_id)
    links = list(doc.reviewer_links)
    if links and not force:
        raise AppError(409, "DOCUMENT_IN_USE", "This file is part of a reviewer. Remove it there first, or force.",
                       reviewer_ids=[l.reviewer_id for l in links],
                       reviewers=[{"id": l.reviewer.id, "title": l.reviewer.title} for l in links])
    if links:
        item_ids = [i.id for i in db.query(SourceItem.id).filter(SourceItem.document_id == doc.id)]
        item_ids = [i[0] if isinstance(i, tuple) else i for i in item_ids]
        if item_ids:
            exam_ids = {r[0] for r in db.query(Question.exam_id).filter(Question.source_item_id.in_(item_ids)).distinct()}
            for eid in exam_ids:
                exam = db.get(Exam, eid)
                if exam is not None:
                    db.delete(exam)
        db.flush()  # the reviewer links go with the document (cascade)
    storage = Path(doc.storage_path).parent if doc.storage_path else None
    db.delete(doc)
    db.commit()
    if storage and storage.exists() and storage.name == doc.id:
        shutil.rmtree(storage, ignore_errors=True)
    return Response(status_code=204)
