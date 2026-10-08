"""Flashcard attempts (BACKEND.md §10, §12 Attempts)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import get_attempt, get_exam
from app.db import get_db
from app.errors import AppError
from app.schemas import AnswerRequest
from app.services import attempts as svc

router = APIRouter(tags=["attempts"])


def _started(db: Session, attempt) -> dict:
    return {
        "attempt_id": attempt.id,
        "exam_id": attempt.exam_id,
        "attempt_no": attempt.attempt_no,
        "kind": attempt.kind,
        "total": attempt.total,
        "card": svc.card_payload(db, attempt, 1),
    }


@router.post("/exams/{exam_id}/attempts", status_code=201)
def start_attempt(exam_id: str, db: Session = Depends(get_db)):
    """Start (or Restart): a new full attempt on the same questions, reshuffled."""
    exam = get_exam(db, exam_id)
    if exam.status != "ready":
        raise AppError(409, "EXAM_NOT_READY", "This exam is not ready yet.", exam_status=exam.status,
                       error_code=exam.error_code)
    if not exam.questions:
        raise AppError(409, "EXAM_NOT_READY", "This exam has no questions.")
    attempt = svc.start_attempt(db, exam, kind="full")
    db.commit()
    return _started(db, attempt)


@router.get("/attempts/{attempt_id}")
def get_map(attempt_id: str, db: Session = Depends(get_db)):
    return svc.map_payload(get_attempt(db, attempt_id))


@router.get("/attempts/{attempt_id}/cards/{index}")
def get_card(attempt_id: str, index: int, db: Session = Depends(get_db)):
    attempt = get_attempt(db, attempt_id)
    card = svc.card_payload(db, attempt, index)
    if attempt.status != "completed":
        attempt.last_viewed_index = index
        db.commit()
    return card


@router.post("/attempts/{attempt_id}/answer")
def answer(attempt_id: str, body: AnswerRequest, db: Session = Depends(get_db)):
    attempt = get_attempt(db, attempt_id)
    return svc.submit_answer(db, attempt, body.question_id, body.response)


@router.post("/attempts/{attempt_id}/finish")
def finish(attempt_id: str, db: Session = Depends(get_db)):
    attempt = get_attempt(db, attempt_id)
    svc.finish(db, attempt)
    return svc.summary_payload(db, attempt)


@router.get("/attempts/{attempt_id}/summary")
def summary(attempt_id: str, db: Session = Depends(get_db)):
    return svc.summary_payload(db, get_attempt(db, attempt_id))


@router.post("/attempts/{attempt_id}/retry-mistakes", status_code=201)
def retry_mistakes(attempt_id: str, db: Session = Depends(get_db)):
    src = get_attempt(db, attempt_id)
    if src.status != "completed":
        raise AppError(409, "ATTEMPT_NOT_FINISHED", "Finish the attempt first.")
    missed = svc.missed_question_ids(src)
    if not missed:
        raise AppError(409, "NO_MISTAKES", "Every card was correct. Nothing to retry.")
    attempt = svc.start_attempt(db, src.exam, kind="mistakes", question_ids=missed, source_attempt=src)
    db.commit()
    return _started(db, attempt)
