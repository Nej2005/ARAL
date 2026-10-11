"""Pick unused items and split them across the chosen question types (BACKEND.md §8.1)."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from app.models import SourceItem
from app.services.generation import QUESTION_TYPES


def fits(it, t: str) -> bool:
    """A quiz question is asked only as written; Identification needs a definition."""
    key = getattr(it, "answer_key", None)
    if key:
        return key.get("type") == t
    return t != "identification" or it.kind == "definition"


def fits_any(it, types) -> bool:
    return any(fits(it, t) for t in types)


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
    by_type = {t: sum(1 for i in unused_in if fits(i, t)) for t in QUESTION_TYPES}
    mx = sum(1 for i in unused_in if fits_any(i, types)) if types else 0
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
    usable = [i for i in unused if fits_any(i, types)]
    if not types or not usable:
        return []
    n = min(count, len(usable))
    want = split_count(n, types)
    remaining = spread_order(usable, rng)
    picked: list[tuple[str, SourceItem]] = []
    taken: set[str] = set()

    # The most constrained type first: Identification takes definitions only, then the others.
    for t in sorted(types, key=lambda t: t != "identification"):
        take = [i for i in remaining if i.id not in taken and fits(i, t)][: want[t]]
        picked += [(t, i) for i in take]
        taken |= {i.id for i in take}

    # If some type was short, top up with whatever is left (spec step 5/6).
    fill_types = [t for t in types if t != "identification"] + [t for t in types if t == "identification"]
    k = 0
    for it in remaining:
        if len(picked) >= n:
            break
        if it.id in taken:
            continue
        options = [t for t in fill_types if fits(it, t)]
        if not options:
            continue
        picked.append((options[k % len(options)], it))
        taken.add(it.id)
        k += 1
    return picked
