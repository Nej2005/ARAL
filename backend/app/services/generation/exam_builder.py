"""Builds all questions of one exam (BACKEND.md §8.5, §8.6, §9)."""

from __future__ import annotations

import logging
import random

from sqlalchemy.orm import Session

from app.models import Document, Exam, Question, Reviewer, SourceItem
from app.services import llm
from app.services.coverage import active_items, used_item_ids
from app.services.fidelity import LessonIndex, check_rationale, norm_cmp, rationale_fallback
from app.services.generation import Draft, TYPE_ORDER
from app.services.generation.batch import GenerationBatch, run_batches
from app.services.generation.identification import build_identification
from app.services.generation.multiple_choice import finish_mcq, prepare_mcq, same_meaning
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
                 rng: random.Random, start_ref: int = 0, best_effort: bool = False,
                 twins: set[str] | None = None) -> list[Draft]:
    drafts = []
    for k, (t, it) in enumerate(pairs):
        d = Draft(ref=f"q{start_ref + k + 1}", type=t, item=it, doc=docs[it.document_id], best_effort=best_effort)
        if t == "identification":
            build_identification(d)
        elif t == "mcq":
            prepare_mcq(d, pool, rng, prefer_meaning=bool(twins and it.id in twins))
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


def _one_per_meaning(pairs: list, spare: list) -> tuple[list, list]:
    """Never two terms with the same definition in one set (e.g. 'Change' and 'Read/Write'):
    the same question would appear twice with different answers. Swap in a spare item instead."""
    kept: list = []
    spare = list(spare)
    for t, it in pairs:
        if any(same_meaning(it, k) for _, k in kept):
            repl = next((s for s in spare if (t != "identification" or s.kind == "definition")
                         and not any(same_meaning(s, k) for _, k in kept)), None)
            if repl is None:
                continue
            spare.remove(repl)
            it = repl
        kept.append((t, it))
    return kept, spare


def _twins(pairs: list) -> dict[str, list[SourceItem]]:
    """Items in the set whose definition matches another item's in the set, with those items."""
    items = [it for _, it in pairs]
    out: dict[str, list[SourceItem]] = {}
    for a in items:
        same = [b for b in items if b.id != a.id and same_meaning(a, b)]
        if same:
            out[a.id] = same
    return out


def _accept_twin_names(drafts: list[Draft], twins: dict[str, list[SourceItem]]) -> None:
    """Identification shows the definition; when another term has the same one, both names are right."""
    for d in drafts:
        if d.type == "identification" and not d.failed and d.item.id in twins:
            seen = {a.casefold() for a in d.accepted_answers}
            for t in twins[d.item.id]:
                for name in [t.term, *(t.aliases or [])]:
                    if name and name.casefold() not in seen:
                        seen.add(name.casefold())
                        d.accepted_answers.append(name)


def _keep_tf_true(drafts: list[Draft]) -> None:
    """Best effort: a false statement that couldn't be made (no Gemini, failed checks) is asked as true."""
    for d in drafts:
        if d.best_effort and d.type == "true_false" and d.is_true is False and d.failed:
            d.failed = None
            build_true(d)
            d.rationale = rationale_fallback(d.item.source_quote)


def build_exam(db: Session, exam: Exam, rng: random.Random | None = None) -> None:
    """Fill `exam.questions`. Raises NothingToSelect or llm.LLMError; the caller sets the status."""
    rng = rng or random.Random()
    reviewer: Reviewer = exam.reviewer
    docs = {d.id: d for d in reviewer.documents}
    all_items = active_items(db, reviewer)
    scoped = filter_items(all_items, exam.scope)
    types = [t for t in exam.question_types]
    best_effort = bool(exam.all_items)
    twins: dict[str, list[SourceItem]] = {}
    if best_effort:
        # "All items": everything in the scope, reviewed or not, twins included (asked by name instead).
        pool = [i for i in scoped if set(types) != {"identification"} or i.kind == "definition"]
        if not pool:
            raise NothingToSelect(0)
        pairs = select(pool, types, len(pool), rng)
        spare: list[SourceItem] = []
        twins = _twins(pairs)
    else:
        used = used_item_ids(db, reviewer)
        unused = [i for i in scoped if i.id not in used]
        if not unused:
            raise NothingToSelect(sum(1 for i in all_items if i.id not in used) - 0)
        pairs = select(unused, types, exam.requested_count, rng)
        picked_ids = {it.id for _, it in pairs}
        spare = [i for i in unused if i.id not in picked_ids]
        pairs, spare = _one_per_meaning(pairs, spare)

    by_id = {i.id: i for i in all_items}
    index = LessonIndex.build(all_items)
    other_statements = {norm_cmp(statement_text(Draft(ref="", type="true_false", item=i, doc=docs[i.document_id])))
                        for i in all_items}
    lesson_terms = sorted({i.term for i in all_items if i.term}, key=str.casefold)

    drafts = _make_drafts(pairs, docs, all_items, rng, best_effort=best_effort, twins=set(twins))
    _accept_twin_names(drafts, twins)
    needs_llm = [d for d in drafts if not d.failed]
    needs_llm.sort(key=lambda d: not (d.type == "true_false" and d.is_true is False))  # Gemini-only work first
    label = f"exam={exam.id[:8]}"
    result = (run_batches(needs_llm, by_id, docs, lesson_terms, label, optional=best_effort)
              if needs_llm else GenerationBatch())
    _apply_batch(drafts, result, by_id, docs, index, other_statements, rng)
    _keep_tf_true(drafts)

    # Rebuild failed questions with spare unused items (§8.5 step 5). Up to three rounds, since a
    # replacement can fail the no-hint checks too. With little time left in this step, the rebuild
    # runs without Gemini: multiple-choice options are already computed, and the explanation falls
    # back to the lesson's own sentence.
    for round_no in range(3):
        failed = [d for d in drafts if d.failed]
        for d in failed:
            log.info("question failed checks (%s): type=%s term=%r", d.failed, d.type, (d.item.term or "")[:50])
        drafts = [d for d in drafts if not d.failed]
        if not failed or not spare:
            break
        kept = [d.item for d in drafts]
        rng.shuffle(spare)
        replacements: list[tuple[str, SourceItem]] = []
        for d in failed:
            taken = kept + [r for _, r in replacements]
            cand = next((x for x in spare if (d.type != "identification" or x.kind == "definition")
                         and not any(same_meaning(x, k) for k in taken)), None)
            if cand is None:
                continue
            spare.remove(cand)
            replacements.append((d.type, cand))
        if not replacements:
            break
        redo = _make_drafts(replacements, docs, all_items, rng, start_ref=1000 * (round_no + 1))
        left = llm.remaining_seconds()
        if left is None or left > 100:
            res2 = run_batches(redo, by_id, docs, lesson_terms, f"{label} redo{round_no + 1}")
        else:
            log.info("rebuilding %d questions without Gemini (%.0fs left in this step)", len(redo), left)
            res2 = GenerationBatch()
        _apply_batch(redo, res2, by_id, docs, index, other_statements, rng)
        drafts += redo
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
