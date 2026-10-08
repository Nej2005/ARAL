"""Background jobs: file extraction and exam generation. Each opens its own DB session."""

from __future__ import annotations

import logging
import traceback
from pathlib import Path

from app.db import SessionLocal
from app.models import Document, DocumentPage, Exam
from app.services import llm
from app.services.generation.exam_builder import NothingToSelect, build_exam
from app.services.ingestion.dedupe import text_sha256
from app.services.ingestion.pdf import extract_pdf
from app.services.ingestion.ppt_convert import PptConversionFailed, PptConversionUnavailable, convert_ppt_to_pptx
from app.services.ingestion.pptx import extract_pptx
from app.services.knowledge import EXTRACTION_VERSION, copy_items, extract_items

log = logging.getLogger("aral.jobs")

MIN_TEXT_CHARS = 200


class IngestError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _read_pages(doc: Document):
    path = Path(doc.storage_path)
    if doc.file_type == "pdf":
        return extract_pdf(path)
    if doc.file_type == "pptx":
        return extract_pptx(path)
    if doc.file_type == "ppt":
        pptx_path = path.with_suffix(".pptx")
        if not pptx_path.exists():
            try:
                pptx_path = convert_ppt_to_pptx(path)
            except PptConversionUnavailable as e:
                raise IngestError("PPT_CONVERSION_UNAVAILABLE", str(e)) from e
            except PptConversionFailed as e:
                raise IngestError("PPT_CONVERSION_FAILED", str(e)) from e
        return extract_pptx(pptx_path)
    raise IngestError("UNSUPPORTED_FILE_TYPE", f"Unsupported file type: {doc.file_type}")


def recover_interrupted() -> int:
    """At startup: jobs that were running when the server last stopped can never finish."""
    db = SessionLocal()
    n = 0
    try:
        for doc in db.query(Document).filter(Document.status.in_(["uploaded", "extracting"])):
            doc.status = "failed"
            doc.error_code = "INTERRUPTED"
            doc.error_message = "Processing was interrupted when the server stopped. Reprocess to continue."
            n += 1
        for exam in db.query(Exam).filter(Exam.status == "generating"):
            exam.status = "failed"
            exam.error_code = "INTERRUPTED"
            exam.error_message = "Generation was interrupted when the server stopped. Create the exam again."
            n += 1
        db.commit()
    finally:
        db.close()
    if n:
        log.warning("marked %d interrupted job(s) as failed", n)
    return n


def extract_document(document_id: str) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return
        doc.status = "extracting"
        doc.error_code = doc.error_message = None
        db.commit()
        try:
            _run_extraction(db, doc)
            doc.status = "ready"
            doc.error_code = doc.error_message = None
            db.commit()
        except IngestError as e:
            _fail(db, doc, e.code, str(e))
        except llm.LLMError as e:
            _fail(db, doc, e.code, str(e))
        except Exception as e:  # noqa: BLE001 - job boundary
            log.error("extraction crashed for %s\n%s", document_id, traceback.format_exc())
            _fail(db, doc, "EXTRACTION_FAILED", f"{type(e).__name__}: {e}")
    finally:
        db.close()


def _fail(db, doc: Document, code: str, message: str) -> None:
    db.rollback()
    doc = db.merge(doc)
    doc.status = "failed"
    doc.error_code = code
    doc.error_message = message[:2000]
    db.commit()


def _run_extraction(db, doc: Document) -> None:
    # Pages: only (re)extract when we have none yet (a resumed job keeps them).
    have_pages = db.query(DocumentPage).filter(DocumentPage.document_id == doc.id).count()
    if not have_pages or doc.extraction_progress == 0:
        db.query(DocumentPage).filter(DocumentPage.document_id == doc.id).delete()
        pages = _read_pages(doc)
        total_chars = sum(len((p.text or "").strip()) for p in pages)
        if total_chars < MIN_TEXT_CHARS:
            raise IngestError("NO_EXTRACTABLE_TEXT",
                              "No readable text was found. Scanned PDFs and image-only slides are not supported yet.")
        for p in pages:
            db.add(DocumentPage(document_id=doc.id, page_no=p.page_no, title=p.title, text=p.text))
        doc.page_count = len(pages)
        doc.text_sha256 = text_sha256([p.text for p in pages])
        doc.extraction_version = EXTRACTION_VERSION
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
            doc.extraction_progress = 10**6
            db.commit()
            log.info("copied %d items from %s to %s (same text)", n, twin.id, doc.id)
            if n == 0:
                raise IngestError("NO_SOURCE_ITEMS", "No definitions or facts were found in this file.")
            return

    extract_items(db, doc)
    db.commit()
    n_items = len([i for i in doc.items if i.superseded_at is None])
    if n_items == 0:
        raise IngestError("NO_SOURCE_ITEMS", "No definitions or facts were found in this file.")


def generate_exam(exam_id: str) -> None:
    db = SessionLocal()
    try:
        exam = db.get(Exam, exam_id)
        if exam is None:
            return
        try:
            build_exam(db, exam)
            if exam.actual_count == 0:
                raise llm.LLMError("No question passed the wording checks. Try again.")
            exam.status = "ready"
            exam.error_code = exam.error_message = None
            db.commit()
        except NothingToSelect as e:
            db.rollback()
            exam = db.merge(exam)
            exam.status = "failed"
            exam.error_code = "ALL_ITEMS_REVIEWED"
            exam.error_message = "Every item in this scope has been part of an exam."
            exam.actual_count = 0
            db.commit()
            log.info("exam %s: nothing to select (outside scope: %d)", exam_id, e.unused_outside_scope)
        except llm.LLMError as e:
            db.rollback()
            exam = db.merge(exam)
            exam.status = "failed"
            exam.error_code = e.code
            exam.error_message = str(e)[:2000]
            db.commit()
        except Exception as e:  # noqa: BLE001
            log.error("generation crashed for %s\n%s", exam_id, traceback.format_exc())
            db.rollback()
            exam = db.merge(exam)
            exam.status = "failed"
            exam.error_code = "GENERATION_FAILED"
            exam.error_message = f"{type(e).__name__}: {e}"[:2000]
            db.commit()
    finally:
        db.close()
