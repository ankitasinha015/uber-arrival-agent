"""Labeled choice-set dataset for validating the axis_spread judge (validate-evaluator).

~40 constructed cases with domain-expert labels (by construction, unambiguous), balanced
Pass/Fail across the four axes and the main failure types. Deterministic (seeded), so
the train/dev/test split is reproducible. PASS = options genuinely vary along the stated
axis; FAIL = near-duplicates or varying on a different axis than stated.
"""

from __future__ import annotations

import random

_CUIS = ["ramen", "Mexican", "Thai", "burger", "American", "pizza", "sushi",
         "Korean BBQ", "Indian", "Greek", "Vietnamese", "Ethiopian"]
_NAMES = ["The Corner", "Maple & Vine", "Eastside", "Little Table", "North End",
          "Favola", "Riverside", "Union", "The Hatch", "Goldfinch", "Second Story", "Alder"]


def _cs(axis, opts):
    return {"axis": axis, "options": [{"restaurant_name": n, "why_this_one": w} for n, w in opts]}


def build(seed: int = 42) -> list[tuple[dict, bool, str]]:
    """Returns [(choice_set, gold_pass, note)]. Balanced, deterministic per seed."""
    _rng = random.Random(seed)

    def _names(k):
        return _rng.sample(_NAMES, k)

    cases: list[tuple[dict, bool, str]] = []

    # --- PASS: genuine spread along the stated axis (5 per axis) ---
    for _ in range(5):
        cz = _rng.sample(_CUIS, 3); nm = _names(3)
        cases.append((_cs("cuisine", list(zip(nm, cz))), True, "distinct cuisines"))
    for _ in range(5):
        nm = _names(3)
        cases.append((_cs("speed_vs_quality",
                           [(nm[0], "grab-and-go, ~10 min"), (nm[1], "sit-down, balanced"),
                            (nm[2], "the best meal here, slower")]), True, "fast→best spread"))
    for _ in range(5):
        nm = _names(3)
        cases.append((_cs("volume",
                           [(nm[0], "a light bite"), (nm[1], "a proper meal"),
                            (nm[2], "a comfort feast")]), True, "light→feast spread"))
    for _ in range(5):
        nm = _names(3)
        cases.append((_cs("familiarity_vs_novelty",
                           [(nm[0], "your usual go-to"), (nm[1], "a new, highly-rated spot"),
                            (nm[2], "an adventurous pick, totally new to you")]), True,
                      "usual→new→adventurous (novelty gradient)"))

    # --- FAIL: near-duplicates or off the stated axis (5 each) ---
    for _ in range(5):
        c = _rng.choice(_CUIS); nm = _names(3)
        cases.append((_cs("cuisine", [(n, c) for n in nm]), False, f"all {c} — no spread"))
    for _ in range(5):
        nm = _names(3); base = _rng.choice([10, 12, 15])
        cases.append((_cs("speed_vs_quality",
                           [(nm[0], f"${base}, quick"), (nm[1], f"${base+12}, quick"),
                            (nm[2], f"${base+30}, quick")]), False, "all fast — varies on price"))
    for _ in range(5):
        nm = _names(3)
        cases.append((_cs("volume",
                           [(nm[0], "a heavy feast"), (nm[1], "a huge feast"),
                            (nm[2], "a giant feast")]), False, "all feasts — no volume spread"))
    for _ in range(5):
        nm = _names(3); ax = _rng.choice(["speed_vs_quality", "cuisine", "volume"])
        cases.append((_cs(ax, [(nm[0], "a good spot nearby"), (nm[1], "also close by"),
                               (nm[2], "another option")]), False, "no axis signal — vague"))

    _rng.shuffle(cases)
    return cases


if __name__ == "__main__":
    d = build()
    npass = sum(1 for _, g, _ in d if g)
    print(f"{len(d)} labeled cases: {npass} Pass, {len(d)-npass} Fail")
