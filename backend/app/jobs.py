"""Processing steps for files and exams.

Nothing runs in the background. The client calls `POST /documents/{id}/process` (one extraction
window per call) and `POST /exams/{id}/process` until the status is `ready` or `failed`. Progress
is saved after every step, so a stopped client simply continues later. This is what makes the app
work the same on localhost and on a serverless host.
"""

from __future__ import annotations

import logging
import traceback
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Document, DocumentPage, Exam, utcnow
from app.services import llm, storage
from app.services.generation.exam_builder import NothingToSelect, build_exam
from app.services.ingestion.dedupe import text_sha256
from app.services.ingestion.pdf import extract_pdf
from app.services.ingestion.ppt_convert import PptConversionFailed, PptConversionUnavailable, convert_ppt_to_pptx
from app.services.ingestion.pptx import extract_pptx
from app.services.knowledge import EXTRACTION_VERSION, copy_items, extract_next_window, window_count

log = logging.getLogger("aral.jobs")

MIN_TEXT_CHARS = 200


class IngestError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- claims (one step at a time)


def _claim(db: Session, obj: Document | Exam) -> bool:
    """Mark the object as being worked on. False if another request holds a fresh claim."""
    now = utcnow()
    started = obj.step_started_at
    if started is not None:
        if started.tzinfo is None:  # SQLite returns naive datetimes
            started = started.replace(tzinfo=now.tzinfo)
        if now - started < timedelta(seconds=settings.step_claim_seconds):
            return False
    obj.step_started_at = now
    db.commit()
    return True


def _release(db: Session, obj: Document | Exam) -> None:
    obj.step_started_at = None
    db.commit()


def is_busy(obj: Document | Exam) -> bool:
    started = obj.step_started_at
    if started is None:
        return False
    now = utcnow()
    if started.tzinfo is None:
        started = started.replace(tzinfo=now.tzinfo)
    return now - started < timedelta(seconds=settings.step_claim_seconds)


def clear_stale_claims() -> int:
    """At startup: claims left behind by a crashed process."""
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        n = 0
        for doc in db.query(Document).filter(Document.step_started_at.isnot(None)):
            doc.step_started_at = None
            n += 1
        for exam in db.query(Exam).filter(Exam.step_started_at.isnot(None)):
            exam.step_started_at = None
            n += 1
        db.commit()
        return n
    finally:
        db.close()


# ---------------------------------------------------------------- documents


def document_pending(doc: Document) -> bool:
    return doc.status in ("uploaded", "extracting")


def document_step(db: Session, doc: Document) -> Document:
    """Advance a document by one step. Returns the (refreshed) document."""
    if not document_pending(doc) or not _claim(db, doc):
        return doc
    try:
        doc.status = "extracting"
        doc.error_code = doc.error_message = None
        db.commit()
        done = _run_step(db, doc)
        if done:
            n_items = sum(1 for i in doc.items if i.superseded_at is None)
            if n_items == 0:
                raise IngestError("NO_SOURCE_ITEMS", "No definitions or facts were found in this file.")
            doc.status = "ready"
        db.commit()
    except IngestError as e:
        _fail(db, doc, e.code, str(e))
    except llm.LLMError as e:
        _fail(db, doc, e.code, str(e))
    except Exception as e:  # noqa: BLE001 - step boundary
        log.error("document step crashed for %s\n%s", doc.id, traceback.format_exc())
        _fail(db, doc, "EXTRACTION_FAILED", f"{type(e).__name__}: {e}")
    finally:
        _release(db, doc)
    return doc


def _fail(db: Session, obj: Document | Exam, code: str, message: str) -> None:
    db.rollback()
    obj = db.merge(obj)
    obj.status = "failed"
    obj.error_code = code
    obj.error_message = message[:2000]
    db.commit()


def _read_pages(db: Session, doc: Document):
    with storage.materialized(db, doc) as path:
        if doc.file_type == "pdf":
            return extract_pdf(path)
        if doc.file_type == "pptx":
            return extract_pptx(path)
        if doc.file_type == "ppt":
            try:
                pptx_path = convert_ppt_to_pptx(path)
            except PptConversionUnavailable as e:
                raise IngestError("PPT_CONVERSION_UNAVAILABLE", str(e)) from e
            except PptConversionFailed as e:
                raise IngestError("PPT_CONVERSION_FAILED", str(e)) from e
            return extract_pptx(pptx_path)
    raise IngestError("UNSUPPORTED_FILE_TYPE", f"Unsupported file type: {doc.file_type}")


def _run_step(db: Session, doc: Document) -> bool:
    """One step. Returns True when the document is fully processed."""
    have_pages = db.query(DocumentPage).filter(DocumentPage.document_id == doc.id).count()
    if not have_pages:
        # Step A: read the file into pages (fast, no Gemini).
        if not storage.has_file(db, doc):
            raise IngestError("FILE_MISSING", "The uploaded file is no longer stored. Upload it again.")
        pages = _read_pages(db, doc)
        total_chars = sum(len((p.text or "").strip()) for p in pages)
        if total_chars < MIN_TEXT_CHARS:
            raise IngestError("NO_EXTRACTABLE_TEXT",
                              "No readable text was found. Scanned PDFs and image-only slides are not supported yet.")
        for p in pages:
            db.add(DocumentPage(document_id=doc.id, page_no=p.page_no, title=p.title, text=p.text))
        doc.page_count = len(pages)
        doc.text_sha256 = text_sha256([p.text for p in pages])
        doc.extraction_version = EXTRACTION_VERSION
        doc.extraction_progress = 0
        storage.drop_file(db, doc)  # the pages are all later steps need
        db.commit()

        # Same text already processed? Copy its items instead of calling Gemini (§5.5).
        twin = (
            db.query(Document)
            .filter(Document.text_sha256 == doc.text_sha256, Document.id != doc.id,
                    Document.status == "ready", Document.extraction_version == EXTRACTION_VERSION)
            .order_by(Document.created_at)
            .first()
        )
        if twin is not None:
            n = copy_items(db, twin, doc)
            doc.copied_from_document_id = twin.id
            doc.extraction_progress = window_count(doc)
            db.commit()
            log.info("copied %d items from %s to %s (same text)", n, twin.id, doc.id)
            return True
        return False

    # Step B..N: one Gemini window per call.
    return extract_next_window(db, doc)


# ---------------------------------------------------------------- exams


def exam_step(db: Session, exam: Exam) -> Exam:
    if exam.status != "generating" or not _claim(db, exam):
        return exam
    try:
        build_exam(db, exam)
        if exam.actual_count == 0:
            raise llm.LLMError("No question passed the wording checks. Try again.")
        exam.status = "ready"
        exam.error_code = exam.error_message = None
        db.commit()
    except NothingToSelect:
        _fail(db, exam, "ALL_ITEMS_REVIEWED", "Every item in this scope has been part of an exam.")
        exam.actual_count = 0
        db.commit()
    except llm.LLMError as e:
        _fail(db, exam, e.code, str(e))
    except Exception as e:  # noqa: BLE001
        log.error("exam step crashed for %s\n%s", exam.id, traceback.format_exc())
        _fail(db, exam, "GENERATION_FAILED", f"{type(e).__name__}: {e}")
    finally:
        _release(db, exam)
    return exam
