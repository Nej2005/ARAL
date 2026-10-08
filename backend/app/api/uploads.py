"""Chunked uploads: start -> PUT chunks -> complete (BACKEND.md §5.1).

Each chunk is a small request (3 MB by default), which keeps uploads under the request-size limit of
serverless hosts. Duplicates are recognized at `start`, before any bytes are sent.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api import get_reviewer
from app.api.documents import create_document, document_summary, file_type_of, find_duplicate, reuse_duplicate
from app.config import settings
from app.db import get_db
from app.errors import AppError, not_found
from app.models import UploadChunk, UploadSession, utcnow
from app.schemas import CompleteUpload, StartUpload
from app.services import storage

router = APIRouter(prefix="/uploads", tags=["uploads"])


def _session(db: Session, upload_id: str) -> UploadSession:
    s = db.get(UploadSession, upload_id)
    if s is None:
        raise not_found("Upload")
    return s


def _sweep_stale(db: Session) -> None:
    cutoff = utcnow() - timedelta(days=1)
    for s in db.query(UploadSession).filter(UploadSession.created_at < cutoff):
        db.delete(s)


@router.post("")
def start_upload(body: StartUpload, db: Session = Depends(get_db)):
    file_type = file_type_of(body.filename)
    if body.size > settings.max_upload_bytes:
        raise AppError(413, "FILE_TOO_LARGE", f"This file is over {settings.max_upload_mb} MB.")
    reviewer = get_reviewer(db, body.reviewer_id) if body.reviewer_id else None
    existing = find_duplicate(db, body.sha256.lower())
    if existing is not None:
        resp = reuse_duplicate(db, existing, reviewer)
        return JSONResponse(status_code=200, content={"upload_id": None, "duplicate": True,
                                                     "document": {**document_summary(db, existing), "duplicate": True},
                                                     "needs_processing": resp.status_code == 202})
    _sweep_stale(db)
    s = UploadSession(filename=body.filename, file_type=file_type, size=body.size, sha256=body.sha256.lower(),
                      chunk_size=settings.upload_chunk_bytes)
    db.add(s)
    db.commit()
    total = -(-body.size // s.chunk_size)
    return {"upload_id": s.id, "duplicate": False, "chunk_size": s.chunk_size, "chunk_count": total}


@router.put("/{upload_id}/chunks/{index}")
async def put_chunk(upload_id: str, index: int, request: Request, db: Session = Depends(get_db)):
    s = _session(db, upload_id)
    total = -(-s.size // s.chunk_size)
    if index < 0 or index >= total:
        raise AppError(400, "BAD_CHUNK", f"Chunk index must be 0..{total - 1}.")
    data = await request.body()
    expected = s.chunk_size if index < total - 1 else s.size - s.chunk_size * (total - 1)
    if len(data) != expected:
        raise AppError(400, "BAD_CHUNK", f"Chunk {index} should be {expected} bytes, got {len(data)}.")
    existing = db.get(UploadChunk, (s.id, index))
    if existing is None:
        db.add(UploadChunk(upload_id=s.id, index=index, data=data))
    else:
        existing.data = data
    db.commit()
    received = db.query(UploadChunk).filter(UploadChunk.upload_id == s.id).count()
    return {"upload_id": s.id, "received_chunks": received, "chunk_count": total}


@router.post("/{upload_id}/complete")
def complete_upload(upload_id: str, body: CompleteUpload | None = None, db: Session = Depends(get_db)):
    s = _session(db, upload_id)
    body = body or CompleteUpload()
    reviewer = get_reviewer(db, body.reviewer_id) if body.reviewer_id else None
    total = -(-s.size // s.chunk_size)
    chunks = {c.index: c.data for c in s.chunks}
    missing = [i for i in range(total) if i not in chunks]
    if missing:
        raise AppError(409, "UPLOAD_INCOMPLETE", f"{len(missing)} chunk(s) missing.", missing=missing[:20])
    data = b"".join(chunks[i] for i in range(total))
    if len(data) != s.size or storage.sha256_bytes(data) != s.sha256:
        db.delete(s)
        db.commit()
        raise AppError(400, "UPLOAD_CORRUPT", "The uploaded bytes do not match. Please upload the file again.")
    if not storage.looks_like(s.file_type, data[:8]):
        db.delete(s)
        db.commit()
        raise AppError(400, "UNSUPPORTED_FILE_TYPE", f"This file does not look like a {s.file_type.upper()} file.")
    existing = find_duplicate(db, s.sha256)
    db.delete(s)
    if existing is not None:  # uploaded twice at the same time
        return reuse_duplicate(db, existing, reviewer)
    doc = create_document(db, s.filename, s.file_type, data, s.sha256, reviewer)
    return JSONResponse(status_code=202, content={**document_summary(db, doc), "duplicate": False})
