"""A deterministic stand-in for Gemini. It answers from the prompt text alone."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel

from app.services.generation.batch import (
    DistractorPick,
    Falsification,
    GeneratedDistractor,
    GeneratedDistractors,
    GenerationBatch,
    QuestionRationale,
)
from app.services.knowledge import ExtractedItem, ExtractionResult

_PAGE = re.compile(r"^=== PAGE (\d+)(?: \| (.*?))? ===$", re.M)
_DEF = re.compile(r"^(?:\s*•\s*)?([A-Z][\w\-]*(?: [\w\-]+)?) [–-] (.+?)\.?$")
_FACT = re.compile(r"^(?:\s*•\s*)?(The .+?)$")
_TABLE = re.compile(r"^([^|]+?) \| (.+)$")


class FakeLLM:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.fail_with: Exception | None = None
        self.bad_rationale_for: set[str] = set()

    def __call__(self, system: str, user: str, schema: type[BaseModel], label: str = "") -> BaseModel:
        self.calls.append((schema.__name__, label))
        if self.fail_with:
            raise self.fail_with
        if schema is ExtractionResult:
            return self._extract(user)
        if schema is GenerationBatch:
            return self._batch(user)
        raise AssertionError(f"unexpected schema {schema}")

    # --- extraction -------------------------------------------------------
    def _extract(self, text: str) -> ExtractionResult:
        items = []
        pos = [(m.start(), int(m.group(1)), m.group(2)) for m in _PAGE.finditer(text)]
        for k, (start, page_no, title) in enumerate(pos):
            end = pos[k + 1][0] if k + 1 < len(pos) else len(text)
            body = text[start:end].split("\n", 1)[1] if "\n" in text[start:end] else ""
            for line in body.splitlines():
                raw = line.strip()
                if not raw or raw == title:
                    continue
                m = _DEF.match(raw)
                if m:
                    items.append(ExtractedItem(kind="definition", page_no=page_no, term=m.group(1),
                                               body=m.group(2), source_quote=raw.lstrip("• "), topic=title))
                    continue
                m = _TABLE.match(raw)
                if m and not raw.lower().startswith("term |"):
                    items.append(ExtractedItem(kind="definition", page_no=page_no, term=m.group(1).strip(),
                                               body=m.group(2).strip(), source_quote=raw, topic=title))
                    continue
                m = _FACT.match(raw)
                if m:
                    sentence = m.group(1)
                    term = re.split(r" (?:is|are|was|takes?|releases?|produces?|has|have) ", sentence[4:], 1)[0]
                    items.append(ExtractedItem(kind="fact", page_no=page_no, term=term.strip(),
                                               body=sentence, source_quote=raw.lstrip("• "), topic=title))
        return ExtractionResult(items=items)

    # --- generation batch -------------------------------------------------
    def _batch(self, user: str) -> GenerationBatch:
        payload = json.loads(user.split("```json\n", 1)[1].rsplit("\n```", 1)[0])
        out = GenerationBatch()
        for q in payload["mcq"]:
            ids = [c["id"] for c in q["candidates"]][:3]
            out.distractor_picks.append(DistractorPick(question_ref=q["question_ref"], distractor_item_ids=ids))
            if q["needs_generated"]:
                out.generated_distractors.append(GeneratedDistractors(
                    question_ref=q["question_ref"],
                    distractors=[GeneratedDistractor(text=f"Made-up option {i + 1}", why_wrong="Not in the lesson.")
                                 for i in range(q["needs_generated"])]))
        for f in payload["false_statements"]:
            stmt = f["statement"]
            words = stmt.rstrip(".").split(" ")
            # Change the last word that is longer than 3 letters (a term or a number).
            idx = next((i for i in range(len(words) - 1, -1, -1) if len(words[i]) > 3 and words[i].isalnum()), len(words) - 1)
            original = words[idx]
            replacement = "nitrogen" if original.lower() != "nitrogen" else "oxygen"
            out.falsifications.append(Falsification(question_ref=f["question_ref"], original_span=original,
                                                    replacement=replacement,
                                                    reason=f"The lesson says {original}, not {replacement}."))
        for q in payload["all_questions"]:
            if q["question_ref"] in self.bad_rationale_for:
                text = "This is wrong because " + " ".join(["word"] * 60)
            else:
                text = f"The lesson defines it this way; the correct answer is {q['correct_answer']}."
            out.rationales.append(QuestionRationale(question_ref=q["question_ref"], rationale=text))
        return out
