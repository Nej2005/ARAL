"""Offline audit: build multiple-choice questions from a term list and count every kind of hint.

    .venv\\Scripts\\python samples\\mcq_audit.py path\\to\\Terms.md [--show N] [--best-effort]

--best-effort audits an "All items" exam: no term is skipped, the smallest hint is kept.

No Gemini calls: distractors are the generator's own top-ranked safe candidates.
"""

from __future__ import annotations

import random
import re
import sys
from collections import Counter
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.services.fidelity import BLANK, LessonIndex, ValidatedItem, dedupe_items, mentions, norm_cmp, too_close  # noqa: E402
from app.services.generation import Draft  # noqa: E402
from app.services.generation.multiple_choice import content_words, finish_mcq, prepare_mcq  # noqa: E402
from app.services.ingestion.markdown import read_markdown  # noqa: E402


def load(path):
    pages, entries = read_markdown(path)
    vals = [ValidatedItem("definition", e.page_no, e.term, [], e.body, e.quote, 0, len(e.quote), e.topic) for e in entries]
    kept, _ = dedupe_items(vals, [])
    items = [SimpleNamespace(id=f"i{k}", term=v.term, aliases=v.aliases, body=v.body, source_quote=v.source_quote,
                             kind=v.kind, topic=v.topic, topic_key=v.topic_key, document_id="d", page_no=v.page_no)
             for k, v in enumerate(kept)]
    return items


def audit(items, rounds=5, show=0, best_effort=False):
    doc = SimpleNamespace(id="d", filename="Terms.md", page_label=lambda n: f"section {n}")
    by_id = {i.id: i for i in items}
    index = LessonIndex.build(items)
    problems = Counter()
    examples: dict[str, list[str]] = {}
    built = failed = 0
    shown = 0
    for seed in range(rounds):
        rng = random.Random(seed)
        for it in items:
            d = prepare_mcq(Draft(ref="q", type="mcq", item=it, doc=doc, best_effort=best_effort), items, rng)
            if not d.failed:
                finish_mcq(d, d.candidate_ids[:3], [], by_id, {"d": doc}, index, rng)
            if d.failed:
                failed += 1
                problems["skipped:" + d.failed] += 1
                continue
            built += 1
            opts = [c["text"] for c in d.choices]
            names = [it.term, *(it.aliases or [])]

            def flag(kind, detail):
                problems[kind] += 1
                examples.setdefault(kind, [])
                if len(examples[kind]) < 3:
                    examples[kind].append(f"{it.term!r}: {detail}")

            if d.mcq_format == "fill_in" and mentions(d.prompt, names):
                flag("stem names the answer", d.prompt[:90])
            for o in opts[1:]:
                if any(too_close(n, o) for n in names) and d.mcq_format == "fill_in":
                    flag("option could also be right", o)
                if mentions(d.prompt.replace("**", ""), [o]) and d.mcq_format == "fill_in":
                    flag("stem names a distractor", o)
            # echo hint: a word of the answer that the question repeats, found in the right option only
            cue_src = d.prompt if d.mcq_format == "fill_in" else opts[0]
            hint = content_words(it.term) & content_words(cue_src.replace(BLANK, " ").replace("**", ""))
            for w in hint:
                if not any(w in content_words(o) for o in opts[1:]):
                    flag("echo word only in the answer", f"'{w}' ({d.mcq_format})")
            # same term, different meaning, asked without saying which
            twins = [x for x in items if x.id != it.id and norm_cmp(x.term) == norm_cmp(it.term)
                     and norm_cmp(x.body) != norm_cmp(it.body)]
            if twins and d.mcq_format == "term_meaning" and "(" not in d.prompt.split("**")[-1]:
                flag("ambiguous term (several meanings)", d.prompt)
            lens = [len(o) for o in opts]
            if lens[0] > 2.2 * max(lens[1:]) or lens[0] * 2.2 < min(lens[1:]):
                flag("length stands out", f"{lens[0]} vs {lens[1:]}")
            if shown < show:
                shown += 1
                print(f"\n[{d.mcq_format}] {it.term!r} — {it.topic}\n  Q: {d.prompt[:220]}")
                for k, o in enumerate(opts):
                    print("   ", "*" if k == 0 else " ", o[:150])
    print(f"\nitems {len(items)} · questions built {built} · skipped {failed} (over {rounds} shuffles)")
    for k, n in problems.most_common():
        print(f"  {n:4}  {k}")
        for ex in examples.get(k, []):
            print("          e.g.", ex)
    return problems


if __name__ == "__main__":
    path = sys.argv[1]
    show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 0
    audit(load(path), show=show, best_effort="--best-effort" in sys.argv)
