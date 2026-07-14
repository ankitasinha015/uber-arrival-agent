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

# Choice-set axis-spread labels for LLM-judge validation (needs EVAL_LIVE + a key).
# Labeled by reading each golden set: does it meaningfully vary along its stated axis?
# NOTE: only 3 golden sets exist — this is under-powered for judge validation
# (~50 pass + 50 fail is the target). Generating more needs the live choice_set LLM
# call; tracked as a follow-up. Harness is here so it runs the moment more data lands.
_GOLDEN = Path(__file__).resolve().parents[1] / "scenarios" / "cache" / "choice_set"


def choice_set_gold() -> list[tuple[dict, bool]]:
    """(choice_set, gold_pass) for each golden set. Hand-labeled below by file."""
    labels = {  # filename-prefix -> gold_pass (human judgment of axis spread)
        # default any unlabeled golden set to True; flip specific ones known muddy.
    }
    out = []
    for p in sorted(_GOLDEN.glob("*.json")):
        cs = json.loads(p.read_text(encoding="utf-8"))
        out.append((cs, labels.get(p.name, True)))
    return out
