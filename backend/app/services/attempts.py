"""Flashcard attempts: cards, grading, feedback, summary (BACKEND.md §10)."""

from __future__ import annotations

import random

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Answer, Attempt, Document, Exam, Question, SourceItem, utcnow
from app.services.coverage import active_items, used_item_ids
from app.services.fidelity import clean_for_display
from app.services.generation import source_ref
from app.services.grading import grade, term_matches


def start_attempt(db: Session, exam: Exam, kind: str = "full", question_ids: list[str] | None = None,
                  source_attempt: Attempt | None = None, rng: random.Random | None = None) -> Attempt:
    rng = rng or random.Random()
    qs = {q.id: q for q in exam.questions}
    ids = list(question_ids) if question_ids is not None else list(qs)
    rng.shuffle(ids)
    choice_orders = {}
    for qid in ids:
        q = qs[qid]
        if q.type == "mcq" and q.choices:
            order = [c["id"] for c in q.choices]
            rng.shuffle(order)
            choice_orders[qid] = order
    attempt = Attempt(
        exam_id=exam.id,
        attempt_no=len(exam.attempts) + 1,
        kind=kind,
        source_attempt_id=source_attempt.id if source_attempt else None,
        question_order=ids,
        choice_orders=choice_orders,
        total=len(ids),
        last_viewed_index=1,
    )
    db.add(attempt)
    db.flush()
    return attempt


# ---------------------------------------------------------------- helpers


def _answers_by_q(attempt: Attempt) -> dict[str, Answer]:
    return {a.question_id: a for a in attempt.answers}


def progress(attempt: Attempt) -> dict:
    answers = attempt.answers
    answered = len(answers)
    return {
        "answered": answered,
        "unanswered": attempt.total - answered,
        "total": attempt.total,
        "correct_count": sum(1 for a in answers if a.is_correct),
    }


def next_unanswered_index(attempt: Attempt, after_index: int) -> int | None:
    """1-based index of the next unanswered card after `after_index`, wrapping around."""
    done = set(_answers_by_q(attempt))
    n = attempt.total
    for k in range(1, n + 1):
        idx = ((after_index - 1 + k) % n) + 1
        if attempt.question_order[idx - 1] not in done:
            return idx
    return None


def question_at(db: Session, attempt: Attempt, index: int) -> Question:
    if index < 1 or index > attempt.total:
        raise AppError(404, "NOT_FOUND", f"Card {index} does not exist (1-{attempt.total}).")
    q = db.get(Question, attempt.question_order[index - 1])
    if q is None:
        raise AppError(404, "NOT_FOUND", "Question not found.")
    return q


def _choice_text(q: Question, cid: str | None) -> str | None:
    if not cid:
        return None
    for c in q.choices or []:
        if c["id"] == cid:
            return c["text"]
    return None


def public_question(attempt: Attempt, q: Question) -> dict:
    """The question without its answer (what an unanswered card shows)."""
    out = {"id": q.id, "type": q.type, "prompt": q.prompt}
    if q.type == "mcq":
        order = attempt.choice_orders.get(q.id) or [c["id"] for c in q.choices or []]
        out["choices"] = [{"id": cid, "text": _choice_text(q, cid)} for cid in order]
    return out


def source_payload(db: Session, q: Question) -> dict:
    exp = q.explanation or {}
    doc = db.get(Document, exp.get("document_id")) if exp.get("document_id") else None
    page_no = exp.get("page_no")
    return {
        "quote": clean_for_display(exp.get("source_quote") or ""),
        "document_id": doc.id if doc else None,
        "filename": doc.filename if doc else None,
        "page_no": page_no,
        "location": doc.page_label(page_no) if doc and page_no else None,
    }


def correct_answer_payload(q: Question) -> dict:
    if q.type == "mcq":
        return {"id": q.correct_answer, "text": _choice_text(q, q.correct_answer)}
    return {"id": None, "text": q.correct_answer}


def your_answer_payload(q: Question, response: str | None) -> dict | None:
    if response is None:
        return None
    if q.type == "mcq":
        return {"id": response, "text": _choice_text(q, response)}
    return {"id": None, "text": response}


def _why_yours_is_wrong(db: Session, q: Question, answer: Answer) -> str | None:
    if answer.is_correct:
        return None
    if q.type == "mcq":
        return (q.choice_feedback or {}).get(answer.response)
    if q.type == "true_false":
        span = (q.explanation or {}).get("changed_span")
        if span and q.correct_answer == "false":
            reason = (q.explanation or {}).get("reason") or ""
            msg = f"The statement changed '{span['from']}' to '{span['to']}'."
            return f"{msg} {reason}".strip()
        return None
    # identification: does the response name another term in the reviewer?
    reviewer = q.exam.reviewer
    docs = {d.id: d for d in reviewer.documents}
    own = q.source_item
    for it in active_items(db, reviewer):
        if it.id == own.id or not it.term:
            continue
        names = [it.term, *(it.aliases or [])]
        if any(term_matches(answer.response, n) for n in names):
            doc = docs.get(it.document_id)
            where = f" ({source_ref(doc, it.page_no)})" if doc else ""
            return f"'{it.term}' is a different concept: {clean_for_display(it.body)}{where}"
    return None


def feedback_payload(db: Session, q: Question, answer: Answer) -> dict:
    exp = q.explanation or {}
    return {
        "is_correct": answer.is_correct,
        "your_answer": your_answer_payload(q, answer.response),
        "correct_answer": correct_answer_payload(q),
        "why": q.rationale,
        "why_yours_is_wrong": _why_yours_is_wrong(db, q, answer),
        "source": source_payload(db, q),
        "changed_span": exp.get("changed_span") if q.correct_answer == "false" else None,
        "match_note": answer.match_note,
    }


def card_payload(db: Session, attempt: Attempt, index: int) -> dict:
    q = question_at(db, attempt, index)
    ans = _answers_by_q(attempt).get(q.id)
    out = {
        "attempt_id": attempt.id,
        "index": index,
        "total": attempt.total,
        "answered": ans is not None,
        "next_unanswered_index": next_unanswered_index(attempt, index),
        "finished": attempt.status == "completed",
        "question": public_question(attempt, q),
    }
    if ans is not None or attempt.status == "completed":
        out["feedback"] = feedback_payload(db, q, ans) if ans is not None else None
        out["correct_answer"] = correct_answer_payload(q)
    return out


def map_payload(attempt: Attempt) -> dict:
    answers = _answers_by_q(attempt)
    cards = []
    for i, qid in enumerate(attempt.question_order, start=1):
        a = answers.get(qid)
        cards.append({"index": i, "question_id": qid,
                      "status": "unanswered" if a is None else ("correct" if a.is_correct else "wrong")})
    return {
        "attempt_id": attempt.id,
        "exam_id": attempt.exam_id,
        "kind": attempt.kind,
        "status": attempt.status,
        "attempt_no": attempt.attempt_no,
        "total": attempt.total,
        "last_viewed_index": attempt.last_viewed_index,
        "progress": progress(attempt),
        "cards": cards,
    }


# ---------------------------------------------------------------- answering


def submit_answer(db: Session, attempt: Attempt, question_id: str, response: str) -> dict:
    if attempt.status == "completed":
        raise AppError(409, "ATTEMPT_COMPLETED", "This attempt is already finished.")
    if question_id not in attempt.question_order:
        raise AppError(404, "NOT_FOUND", "That question is not part of this attempt.")
    if question_id in _answers_by_q(attempt):
        raise AppError(409, "ALREADY_ANSWERED", "This card was already answered. Answers cannot be changed.")
    q = db.get(Question, question_id)
    is_correct, note = grade(q.type, q.correct_answer, q.accepted_answers, response)
    ans = Answer(attempt_id=attempt.id, question_id=q.id, response=response.strip(), is_correct=is_correct,
                 match_note=note)
    db.add(ans)
    attempt.answers.append(ans)
    attempt.correct_count = sum(1 for a in attempt.answers if a.is_correct)
    index = attempt.question_order.index(question_id) + 1
    attempt.last_viewed_index = index
    nxt = next_unanswered_index(attempt, index)
    finished = nxt is None
    if finished:
        attempt.status = "completed"
        attempt.completed_at = utcnow()
    db.commit()
    return {
        "feedback": feedback_payload(db, q, ans),
        "progress": progress(attempt),
        "next_unanswered_index": nxt,
        "finished": finished,
    }


def finish(db: Session, attempt: Attempt) -> None:
    if attempt.status != "completed":
        attempt.status = "completed"
        attempt.completed_at = utcnow()
        attempt.correct_count = sum(1 for a in attempt.answers if a.is_correct)
        db.commit()


def missed_question_ids(attempt: Attempt) -> list[str]:
    """Wrong + skipped, in the attempt's order."""
    answers = _answers_by_q(attempt)
    return [qid for qid in attempt.question_order if qid not in answers or not answers[qid].is_correct]


def summary_payload(db: Session, attempt: Attempt) -> dict:
    if attempt.status != "completed":
        raise AppError(409, "ATTEMPT_NOT_FINISHED", "Finish the attempt first.")
    answers = _answers_by_q(attempt)
    wrong, skipped = [], []
    for qid in attempt.question_order:
        q = db.get(Question, qid)
        a = answers.get(qid)
        if a is not None and a.is_correct:
            continue
        card = {
            "question_id": q.id,
            "type": q.type,
            "prompt": q.prompt,
            "your_answer": your_answer_payload(q, a.response if a else None),
            "correct_answer": correct_answer_payload(q),
            "why": q.rationale,
            "why_yours_is_wrong": _why_yours_is_wrong(db, q, a) if a else None,
            "source": source_payload(db, q),
            "changed_span": (q.explanation or {}).get("changed_span") if q.correct_answer == "false" else None,
        }
        (wrong if a is not None else skipped).append(card)
    reviewer = attempt.exam.reviewer
    used = used_item_ids(db, reviewer)
    unused = sum(1 for i in active_items(db, reviewer) if i.id not in used)
    total = attempt.total or 1
    return {
        "attempt_id": attempt.id,
        "exam_id": attempt.exam_id,
        "kind": attempt.kind,
        "attempt_no": attempt.attempt_no,
        "correct_count": attempt.correct_count,
        "answered": len(answers),
        "skipped": len(skipped),
        "total": attempt.total,
        "percent": round(100 * attempt.correct_count / total),
        "wrong_cards": wrong,
        "skipped_cards": skipped,
        "retry_mistakes": {"count": len(wrong) + len(skipped)},
        "next_set": {"unused_items": unused, "all_items": attempt.exam.all_items},
    }


def exam_scores(exam: Exam) -> dict:
    completed = [a for a in exam.attempts if a.status == "completed"]
    full = [a for a in completed if a.kind == "full"]
    best = max(full, key=lambda a: (a.correct_count / (a.total or 1), a.completed_at), default=None)
    latest = max(completed, key=lambda a: a.completed_at, default=None)
    return {
        "attempt_count": len(exam.attempts),
        "best_score": {"correct_count": best.correct_count, "total": best.total} if best else None,
        "latest_score": {"correct_count": latest.correct_count, "total": latest.total, "kind": latest.kind}
        if latest else None,
        "latest_attempt_id": latest.id if latest else None,
        "in_progress_attempt_id": next((a.id for a in reversed(exam.attempts) if a.status == "in_progress"), None),
    }
