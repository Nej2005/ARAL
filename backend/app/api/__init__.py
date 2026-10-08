from sqlalchemy.orm import Session

from app.errors import not_found
from app.models import Attempt, Document, Exam, Reviewer


def get_document(db: Session, document_id: str) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise not_found("Document")
    return doc


def get_reviewer(db: Session, reviewer_id: str) -> Reviewer:
    r = db.get(Reviewer, reviewer_id)
    if r is None:
        raise not_found("Reviewer")
    return r


def get_exam(db: Session, exam_id: str) -> Exam:
    e = db.get(Exam, exam_id)
    if e is None:
        raise not_found("Exam")
    return e


def get_attempt(db: Session, attempt_id: str) -> Attempt:
    a = db.get(Attempt, attempt_id)
    if a is None:
        raise not_found("Attempt")
    return a
