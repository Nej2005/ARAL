"""The one batched Gemini call per exam: distractor picks, falsifications, rationales (§8.5)."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.models import Document, SourceItem
from app.services import llm
from app.services.fidelity import clean_for_display
from app.services.generation import Draft
from app.services.generation.true_false import statement_text


class DistractorPick(BaseModel):
    question_ref: str
    distractor_item_ids: list[str] = Field(description="Exactly 3 ids from the question's candidate list, most plausible first.")


class GeneratedDistractor(BaseModel):
    text: str = Field(description="A plausible but wrong option, in the same style as the correct one.")
    why_wrong: str = Field(description="One short sentence on why this option is wrong.")


class GeneratedDistractors(BaseModel):
    question_ref: str
    distractors: list[GeneratedDistractor]


class Falsification(BaseModel):
    question_ref: str
    original_span: str = Field(description="A span copied exactly from the statement.")
    replacement: str = Field(description="What to put in its place; preferably another term from this lesson, a changed number, or a negation.")
    reason: str = Field(description="One short sentence on why the edited statement is false.")


class QuestionRationale(BaseModel):
    question_ref: str
    rationale: str = Field(description="1-2 sentences, at most 40 words, grounded ONLY in the given source text.")


class GenerationBatch(BaseModel):
    distractor_picks: list[DistractorPick] = Field(default_factory=list)
    generated_distractors: list[GeneratedDistractors] = Field(default_factory=list)
    falsifications: list[Falsification] = Field(default_factory=list)
    rationales: list[QuestionRationale] = Field(default_factory=list)


BATCH_RULES = """You help build an exam reviewer from lesson material. You receive a JSON object describing questions.
Return a JSON object with these lists:

1. distractor_picks: for every entry in "mcq", choose EXACTLY 3 candidate ids that make the most plausible wrong
   options: same topic, same kind of thing (a term for a term, a definition for a definition), similar length
   and wording style to the correct option. Use only ids from that question's "candidates".
   NEVER pick a candidate that is also a correct answer for the stem: a synonym, an abbreviation or expansion
   of the answer, a broader or narrower name for the same thing, or a statement that is also true for it.
   Never pick a candidate that the stem itself names or rules out.
2. generated_distractors: ONLY for "mcq" entries whose "needs_generated" > 0, write that many plausible wrong options
   in the style and length of the correct option, plus one short sentence each on why it is wrong. They must be
   clearly wrong for the stem, must not contain the answer or its synonyms, and must not be named in the stem.
3. falsifications: for every entry in "false_statements", change the statement so it becomes FALSE by replacing ONE
   span. "original_span" must be copied exactly from the statement (a key term, a number, a place, a relationship word).
   "replacement" should preferably be another term from this lesson (see "lesson_terms"), a changed number, or a
   negation. Keep everything else identical. Do not pick a replacement that makes the sentence true in another way.
   Add a one-sentence reason why the edited statement is false.
4. rationales: for EVERY entry in "all_questions", write 1-2 sentences (max 40 words) on why the correct answer is
   right, using ONLY the given source text. Do not add outside facts. For a false statement, say what the lesson
   actually states.

Use the given question_ref values exactly. Return only JSON.
"""


def build_payload(drafts: list[Draft], by_id: dict[str, SourceItem], docs: dict[str, Document],
                  lesson_terms: list[str]) -> dict:
    mcq, false_stmts, all_q = [], [], []
    for d in drafts:
        it = d.item
        entry = {"question_ref": d.ref, "type": d.type, "source_text": clean_for_display(it.source_quote),
                 "term": it.term}
        if d.type == "mcq" and not d.failed:
            corr = {"text": d.choices[0]["text"], "kind": "term" if d.mcq_format == "fill_in" else "definition"}
            cands = [{"id": cid, "text": d.candidate_texts[cid], "topic": by_id[cid].topic}
                     for cid in d.candidate_ids if cid in by_id and cid in d.candidate_texts]
            mcq.append({"question_ref": d.ref, "stem": d.prompt, "correct": corr, "topic": it.topic,
                        "candidates": cands, "needs_generated": d.needs_generated})
            entry["correct_answer"] = corr["text"]
        elif d.type == "true_false":
            stmt = statement_text(d)
            entry["statement"] = stmt
            if d.is_true is False:
                false_stmts.append({"question_ref": d.ref, "statement": stmt, "topic": it.topic})
                entry["correct_answer"] = "FALSE (after the edit)"
            else:
                entry["correct_answer"] = "TRUE"
        else:
            entry["definition"] = clean_for_display(it.body)
            entry["correct_answer"] = it.term
        all_q.append(entry)
    return {"mcq": mcq, "false_statements": false_stmts, "all_questions": all_q, "lesson_terms": lesson_terms[:150]}


def run_batch(payload: dict, label: str) -> GenerationBatch:
    user = "Build the exam parts for this data.\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    return llm.generate_structured(BATCH_RULES, user, GenerationBatch, label)


def run_batches(drafts: list[Draft], by_id, docs, lesson_terms: list[str], label: str, size: int = 25) -> GenerationBatch:
    merged = GenerationBatch()
    for i in range(0, len(drafts), size):
        chunk = drafts[i : i + size]
        part = run_batch(build_payload(chunk, by_id, docs, lesson_terms), f"{label} batch={i // size + 1}")
        merged.distractor_picks += part.distractor_picks
        merged.generated_distractors += part.generated_distractors
        merged.falsifications += part.falsifications
        merged.rationales += part.rationales
    return merged
