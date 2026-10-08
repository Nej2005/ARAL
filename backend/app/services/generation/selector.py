"""Pick unused items and split them across the chosen question types (BACKEND.md §8.1)."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from app.models import SourceItem
from app.services.generation import QUESTION_TYPES


@dataclass
class Availability:
    total_items: int
    used_items: int
    unused_items: int           # unused inside the scope
    unused_outside_scope: int   # unused items the scope excludes
    unused_by_type: dict[str, int]
    max_count_for_types: int


def availability(pool: list[SourceItem], all_items: list[SourceItem], used: set[str], types: list[str]) -> Availability:
    unused_in = [i for i in pool if i.id not in used]
    unused_all = [i for i in all_items if i.id not in used]
    defs = sum(1 for i in unused_in if i.kind == "definition")
    by_type = {"mcq": len(unused_in), "true_false": len(unused_in), "identification": defs}
    if not types:
        mx = 0
    elif set(types) == {"identification"}:
        mx = defs
    else:
        mx = len(unused_in)
    return Availability(
        total_items=len(all_items),
        used_items=sum(1 for i in all_items if i.id in used),
        unused_items=len(unused_in),
        unused_outside_scope=len(unused_all) - len(unused_in),
        unused_by_type=by_type,
        max_count_for_types=mx,
    )


def split_count(count: int, types: list[str]) -> dict[str, int]:
    """Even split in the order given; the remainder goes to the first types."""
    n = len(types)
    base, rem = divmod(count, n)
    return {t: base + (1 if i < rem else 0) for i, t in enumerate(types)}


def spread_order(items: list[SourceItem], rng: random.Random) -> list[SourceItem]:
    """Random order that round-robins across (document, page) so one exam covers everything."""
    groups: dict[tuple[str, int], list[SourceItem]] = defaultdict(list)
    for it in items:
        groups[(it.document_id, it.page_no)].append(it)
    keys = list(groups)
    rng.shuffle(keys)
    for k in keys:
        rng.shuffle(groups[k])
    out: list[SourceItem] = []
    while keys:
        next_keys = []
        for k in keys:
            out.append(groups[k].pop())
            if groups[k]:
                next_keys.append(k)
        keys = next_keys
    return out


def select(unused: list[SourceItem], types: list[str], count: int, rng: random.Random | None = None) -> list[tuple[str, SourceItem]]:
    """Returns [(type, item)] with len <= count. Fills Identification first (definitions only)."""
    rng = rng or random.Random()
    types = [t for t in types if t in QUESTION_TYPES]
    if not types or not unused:
        return []
    want = split_count(min(count, len(unused)), types)
    remaining = spread_order(unused, rng)
    picked: list[tuple[str, SourceItem]] = []

    if "identification" in want:
        defs = [i for i in remaining if i.kind == "definition"]
        take = defs[: want["identification"]]
        picked += [("identification", i) for i in take]
        taken = {i.id for i in take}
        remaining = [i for i in remaining if i.id not in taken]
        shortfall = want["identification"] - len(take)
        others = [t for t in types if t != "identification"]
        if shortfall and others:
            for k, t in enumerate(others):
                want[t] += shortfall // len(others) + (1 if k < shortfall % len(others) else 0)

    for t in types:
        if t == "identification":
            continue
        take = remaining[: want[t]]
        picked += [(t, i) for i in take]
        remaining = remaining[len(take):]

    # If some type was short, top up with whatever is left (spec step 5/6).
    missing = min(count, len(unused)) - len(picked)
    if missing > 0 and remaining:
        fill_types = [t for t in types if t != "identification"] or ["identification"]
        for k, it in enumerate(remaining[:missing]):
            t = fill_types[k % len(fill_types)]
            if t == "identification" and it.kind != "definition":
                continue
            picked.append((t, it))
    return picked
