"""Labeled gold data — the eval-audit "Labeled Data" fix.

Human (domain-expert) judgments for validating the evaluators. `gold_pass=True`
means the output is CORRECT and the evaluator should PASS it; `False` means a real
failure the evaluator should CATCH. Both classes are present so validation can
measure TPR (failures caught) AND TNR (good outputs not falsely flagged) — not raw
accuracy, which class imbalance makes misleading.

Cases are grounded in the failure taxonomy from error analysis on the synthetic
traces (synthetic/FINDINGS.md), including the real cuisine-misclassification bug.
"""

from __future__ import annotations

import json
from pathlib import Path

# (claimed_cuisine, categories, badged, gold_pass, note)
CUISINE_MATCH_GOLD = [
    ("Burger", ["Burger Joint"], True, True, "Shake Shack — burger place, burger claim"),
    ("Mexican", ["Taco Restaurant"], True, True, "taqueria matched Mexican"),
    ("American", ["American Restaurant"], True, True, "genuine American"),
    ("Ramen", ["Ramen Restaurant"], True, True, "ramen place, ramen claim"),
    ("Pizza", ["Pizzeria"], True, True, "pizzeria matched Pizza"),
    ("Korean BBQ", ["Korean BBQ Restaurant"], False, True, "honest label, not badged — OK"),
    ("Steakhouse", ["Steakhouse"], False, True, "honest label, not badged — OK"),
    # real failures the evaluator must catch:
    ("American", ["Korean BBQ Restaurant"], True, False, "BUG: Korean BBQ tagged American"),
    ("American", ["Sushi Restaurant"], True, False, "sushi tagged American"),
    ("Ramen", ["Mexican Restaurant"], True, False, "clear cuisine mismatch"),
    ("Pizza", ["Steakhouse"], True, False, "steakhouse claimed as Pizza"),
]

# Realistic 6-cuisine taste orders (full profiles, like the app uses).
_MEX = ["Mexican", "Thai", "Pizza", "American", "Burger", "Ramen"]
_BUR = ["Burger", "American", "Pizza", "Mexican", "Thai", "Ramen"]
_RAM = ["Ramen", "Thai", "Mexican", "Burger", "American", "Pizza"]

# (why, claimed_cuisine, pref, gold_pass, note). 'a lot' is honest only for a
# top-half cuisine; 'most' only for #1.
HONEST_COPY_GOLD = [
    ("you order burger most on Uber Eats — 700 m away", "Burger", _BUR, True, "burger IS #1"),
    ("you order ramen most on Uber Eats — 200 m away", "Ramen", _RAM, True, "ramen IS #1"),
    ("closest to your taste that's open near your hotel — you order pizza a lot — 300 m",
     "Pizza", _MEX, True, "'a lot', pizza is #3 of 6 (top half) — honest"),
    ("Pizza · a cuisine you order often — 500 m away", "Pizza", _MEX, True, "no frequency claim"),
    ("Ramen · the closest open option to your taste — 300 m away", "Ramen", _BUR, True,
     "neutral copy for a #6 cuisine — no claim, OK"),
    # real failures:
    ("you order pizza most on Uber Eats — 300 m away", "Pizza", _MEX, False, "FALSE 'most': pizza is #3"),
    ("you order american most on Uber Eats — 900 m away", "American", _MEX, False, "FALSE 'most': american is #4"),
    ("you order ramen a lot — 300 m away", "Ramen", _BUR, False, "FALSE 'a lot': ramen is #6 (bottom half)"),
]

_GOLDEN = Path(__file__).resolve().parents[1] / "scenarios" / "cache" / "choice_set"


def _cs(axis, opts):
    return {"axis": axis, "options": [{"restaurant_name": n, "why_this_one": w} for n, w in opts]}


# Labeled choice sets for validating the axis_spread LLM judge — both classes, across
# all four axes. PASS = options meaningfully vary along the stated axis; FAIL =
# near-duplicates or varying on a DIFFERENT axis than the one stated.
AXIS_SPREAD_GOLD = [
    # --- PASS: genuine spread along the stated axis ---
    (_cs("cuisine", [("Ippudo", "ramen — your usual"), ("Tropisueño", "Mexican"),
                     ("Joe's Pizza", "pizza")]), True, "three distinct cuisines"),
    (_cs("speed_vs_quality", [("Ramen Counter", "grab-and-go, ~10 min"),
                              ("Corner Bistro", "sit-down, balanced"),
                              ("The Grille", "a real feast, slower")]), True, "fast→best spread"),
    (_cs("volume", [("Onigiri Bar", "a light bite"), ("Bento House", "a proper meal"),
                    ("Smokehouse", "a comfort feast")]), True, "light→feast spread"),
    (_cs("familiarity_vs_novelty", [("Pad Thai Palace", "your usual go-to"),
                                    ("Izakaya Mori", "new, highly-rated"),
                                    ("Green Bowl", "a light salad")]), True, "usual/new/light spread"),
    (_cs("cuisine", [("In-N-Out", "burger"), ("Osha Thai", "Thai"),
                     ("Tacos El Gordo", "Mexican")]), True, "distinct cuisines"),
    (_cs("speed_vs_quality", [("24h Diner", "fast, always open"),
                              ("Neighborhood Trattoria", "balanced"),
                              ("Tasting Room", "the best meal, slow")]), True, "fast→best spread"),
    # --- FAIL: near-duplicates or off the stated axis ---
    (_cs("cuisine", [("Shake Shack", "burger"), ("Five Guys", "burger"),
                     ("Super Duper", "burger")]), False, "all burger — no cuisine spread"),
    (_cs("speed_vs_quality", [("Cheap Counter", "$10, fast"), ("Mid Spot", "$20, fast"),
                              ("Pricey Place", "$40, fast")]), False, "all fast — varies on PRICE not speed"),
    (_cs("volume", [("Big Burger", "a heavy feast"), ("Double Stack", "a heavy feast"),
                    ("Triple Co.", "a heavy feast")]), False, "all feasts — no volume spread"),
    (_cs("cuisine", [("Joe's Pizza", "pizza"), ("Tony's Pizza", "pizza"),
                     ("Prince St Pizza", "pizza")]), False, "all pizza — no spread"),
    (_cs("familiarity_vs_novelty", [("Your Ramen Spot", "your usual"),
                                    ("Ramen Two", "another usual ramen"),
                                    ("Ramen Three", "your regular ramen")]), False, "all familiar — no novelty"),
    (_cs("speed_vs_quality", [("A Good Spot", "a good spot nearby"),
                              ("Another Option", "also nearby"),
                              ("One More", "close by too")]), False, "no axis signal — vague/off-axis"),
]


def choice_set_gold() -> list[tuple[dict, bool]]:
    """Labeled choice sets for axis_spread judge validation: the balanced constructed
    set above, plus the real golden sets (labeled pass — they passed the property gate
    and read as genuine cuisine spreads)."""
    out = list((cs, g) for cs, g, _ in AXIS_SPREAD_GOLD)
    for p in sorted(_GOLDEN.glob("*.json")):
        out.append((json.loads(p.read_text(encoding="utf-8")), True))
    return out
