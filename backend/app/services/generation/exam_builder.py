"""Builds all questions of one exam (BACKEND.md §8.5, §8.6, §9)."""

from __future__ import annotations

import logging
import random

from sqlalchemy.orm import Session

from app.models import Document, Exam, Question, Reviewer, SourceItem
from app.services.coverage import active_items, used_item_ids
from app.services.fidelity import LessonIndex, check_rationale, norm_cmp, rationale_fallback
from app.services.generation import Draft, TYPE_ORDER
from app.services.generation.batch import GenerationBatch, run_batches
from app.services.generation.identification import build_identification
from app.services.generation.multiple_choice import finish_mcq, prepare_mcq
from app.services.generation.selector import select
from app.services.generation.true_false import build_false, build_true, statement_text
from app.services.scope import filter_items

log = logging.getLogger("aral.generation")


class NothingToSelect(Exception):
    def __init__(self, unused_outside_scope: int):
        super().__init__("All items reviewed")
        self.unused_outside_scope = unused_outside_scope


def _assign_tf(drafts: list[Draft], rng: random.Random) -> None:
    """About half true, half false, never all the same when there are 2+ (§8.4)."""
    tf = [d for d in drafts if d.type == "true_false"]
    if not tf:
        return
    n_false = len(tf) // 2 if len(tf) % 2 == 0 else len(tf) // 2 + rng.randint(0, 1)
    if len(tf) >= 2:
        n_false = max(1, min(len(tf) - 1, n_false))
    else:
        n_false = rng.randint(0, 1)
    rng.shuffle(tf)
    for i, d in enumerate(tf):
        d.is_true = i >= n_false


def _make_drafts(pairs: list[tuple[str, SourceItem]], docs: dict[str, Document], pool: list[SourceItem],
                 rng: random.Random, start_ref: int = 0) -> list[Draft]:
    drafts = []
    for k, (t, it) in enumerate(pairs):
        d = Draft(ref=f"q{start_ref + k + 1}", type=t, item=it, doc=docs[it.document_id])
        if t == "identification":
            build_identification(d)
        elif t == "mcq":
            prepare_mcq(d, pool, rng)
        drafts.append(d)
    _assign_tf([d for d in drafts if d.type == "true_false"], rng)
    for d in drafts:
        if d.type == "true_false" and d.is_true:
            build_true(d)
    return drafts


def _apply_batch(drafts: list[Draft], result: GenerationBatch, by_id, docs, index: LessonIndex,
                 other_statements: set[str], rng: random.Random) -> None:
    picks = {p.question_ref: p.distractor_item_ids for p in result.distractor_picks}
    gens = {g.question_ref: [(x.text, x.why_wrong) for x in g.distractors] for g in result.generated_distractors}
    fals = {f.question_ref: f for f in result.falsifications}
    rats = {r.question_ref: r.rationale for r in result.rationales}
    for d in drafts:
        if d.failed:
            continue
        if d.type == "mcq":
            finish_mcq(d, picks.get(d.ref, []), gens.get(d.ref, []), by_id, docs, index, rng)
        elif d.type == "true_false" and d.is_true is False:
            f = fals.get(d.ref)
            if f is None:
                d.failed = "tf_no_falsification"
            else:
                build_false(d, f.original_span, f.replacement, f.reason, other_statements)
        if d.failed:
            continue
        forbidden = None
        if d.type == "true_false" and d.is_true is False:
            forbidden = (d.explanation.get("changed_span") or {}).get("to")
        r = rats.get(d.ref, "")
        d.rationale = r if check_rationale(r, index.text_norm, forbidden) else rationale_fallback(d.item.source_quote)


def build_exam(db: Session, exam: Exam, rng: random.Random | None = None) -> None:
    """Fill `exam.questions`. Raises NothingToSelect or llm.LLMError; the caller sets the status."""
    rng = rng or random.Random()
    reviewer: Reviewer = exam.reviewer
    docs = {d.id: d for d in reviewer.documents}
    all_items = active_items(db, reviewer)
    used = used_item_ids(db, reviewer)
    scoped = filter_items(all_items, exam.scope)
    unused = [i for i in scoped if i.id not in used]
    if not unused:
        raise NothingToSelect(sum(1 for i in all_items if i.id not in used) - 0)
    types = [t for t in exam.question_types]
    pairs = select(unused, types, exam.requested_count, rng)
    picked_ids = {it.id for _, it in pairs}
    spare = [i for i in unused if i.id not in picked_ids]

    by_id = {i.id: i for i in all_items}
    index = LessonIndex.build(all_items)
    other_statements = {norm_cmp(statement_text(Draft(ref="", type="true_false", item=i, doc=docs[i.document_id])))
                        for i in all_items}
    lesson_terms = sorted({i.term for i in all_items if i.term}, key=str.casefold)

    drafts = _make_drafts(pairs, docs, all_items, rng)
    needs_llm = [d for d in drafts if not d.failed and (d.type == "mcq" or (d.type == "true_false" and d.is_true is False) or True)]
    label = f"exam={exam.id[:8]}"
    result = run_batches(needs_llm, by_id, docs, lesson_terms, label) if needs_llm else GenerationBatch()
    _apply_batch(drafts, result, by_id, docs, index, other_statements, rng)

    # One rebuild round for failed questions, using spare unused items (§8.5 step 5).
    failed = [d for d in drafts if d.failed]
    for d in failed:
        log.info("question failed fidelity (%s): type=%s term=%r", d.failed, d.type, (d.item.term or "")[:50])
    if failed and spare:
        log.info("rebuilding %d failed questions with spare items", len(failed))
        rng.shuffle(spare)
        replacements: list[tuple[str, SourceItem]] = []
        for d in failed:
            cand = next((s for s in spare if d.type != "identification" or s.kind == "definition"), None)
            if cand is None:
                continue
            spare.remove(cand)
            replacements.append((d.type, cand))
        if replacements:
            redo = _make_drafts(replacements, docs, all_items, rng, start_ref=len(drafts))
            res2 = run_batches(redo, by_id, docs, lesson_terms, label + " redo")
            _apply_batch(redo, res2, by_id, docs, index, other_statements, rng)
            drafts = [d for d in drafts if not d.failed] + [d for d in redo if not d.failed]
        else:
            drafts = [d for d in drafts if not d.failed]
    else:
        drafts = [d for d in drafts if not d.failed]

    # Printable order: grouped by type (MCQ, T/F, Identification), as on a school exam.
    drafts.sort(key=lambda d: TYPE_ORDER[d.type])
    for pos, d in enumerate(drafts, start=1):
        db.add(Question(
            exam_id=exam.id, source_item_id=d.item.id, type=d.type, position=pos, prompt=d.prompt,
            choices=d.choices, correct_answer=d.correct_answer, accepted_answers=d.accepted_answers,
            rationale=d.rationale, choice_feedback=d.choice_feedback, explanation=d.explanation,
        ))
    exam.actual_count = len(drafts)
