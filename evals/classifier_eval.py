"""Synthetic stress-test for the confidence-gated vector cuisine classifier
(generate-synthetic-data → run through the pipeline → measure by failure cell).

The classifier was calibrated on ~9 hand-picked places. This expands to ~40 labeled
restaurants generated across three dimensions that target where a THRESHOLD classifier
breaks:

  D1 true cuisine   — in-set (should confidently match one of the 6 taste cuisines)
                      vs out-of-set (should return None, never a forced taste badge)
  D2 category clarity— explicit / generic / misleading-overlap / branded-only
  D3 name style     — encodes-cuisine / neutral / cross-cuisine-misleading

Two failure modes matter most:
  * out-of-set FALSE MATCH — an ambiguous place wrongly badged as a taste cuisine
    (the honesty failure the whole design exists to prevent). Must be ~0.
  * in-set FALSE REJECT — a real taste match dropped to None (recall cost of the
    conservative threshold). Tolerable, but measured honestly.

Run: CONCIERGE_CHROMA=1 HF_HUB_OFFLINE=1 python -m evals.classifier_eval
"""

from __future__ import annotations

import os
from collections import defaultdict

# (name, categories, true_cuisine|None, clarity, name_style)
DATA = [
    # --- in-set: Ramen ---
    ("Tokyo Ramen House", ["Ramen Restaurant"], "Ramen", "explicit", "encodes"),
    ("Slurp", ["Ramen Restaurant"], "Ramen", "explicit", "neutral"),
    ("Ivan's Ramen Bar", ["Japanese Restaurant", "Ramen Restaurant"], "Ramen", "explicit", "encodes"),
    ("Broth & Co", ["Noodle House"], "Ramen", "misleading", "neutral"),
    # --- in-set: Mexican ---
    ("La Taqueria", ["Mexican Restaurant"], "Mexican", "explicit", "encodes"),
    ("Union & Vine", ["Taco Restaurant"], "Mexican", "explicit", "neutral"),
    ("El Farolito", ["Restaurant"], "Mexican", "generic", "encodes"),
    ("Burrito Bros", ["Fast Food Restaurant"], "Mexican", "misleading", "encodes"),
    # --- in-set: Thai ---
    ("Riverside Kitchen", ["Thai Restaurant"], "Thai", "explicit", "neutral"),
    ("Bangkok House", ["Thai Restaurant"], "Thai", "explicit", "encodes"),
    ("Golden Noodle", ["Noodle House"], "Thai", "misleading", "neutral"),
    ("Spice Garden", ["Restaurant"], "Thai", "generic", "neutral"),
    # --- in-set: Burger ---
    ("The Patty Corner", ["Burger Joint"], "Burger", "explicit", "neutral"),
    ("Shake Shack", ["Burger Joint", "Fast Food Restaurant"], "Burger", "explicit", "neutral"),
    ("Bangkok Burger", ["Burger Joint"], "Burger", "explicit", "misleading"),
    ("Grind House", ["American Restaurant", "Burger Joint"], "Burger", "explicit", "neutral"),
    # --- in-set: American ---
    ("The Smith", ["American Restaurant"], "American", "explicit", "neutral"),
    ("The Hatch", ["Diner"], "American", "generic", "neutral"),
    ("All-American Grill", ["Restaurant"], "American", "branded", "encodes"),
    ("Smokehouse 61", ["BBQ Joint"], "American", "misleading", "neutral"),
    ("Keens Steakhouse", ["Steakhouse"], "American", "misleading", "neutral"),
    # --- in-set: Pizza ---
    ("Joe's Pizza", ["Pizzeria"], "Pizza", "explicit", "encodes"),
    ("Nonna's Slice", ["Restaurant"], "Pizza", "branded", "encodes"),
    ("American Pie", ["Pizzeria"], "Pizza", "explicit", "misleading"),
    ("Roma Trattoria", ["Italian Restaurant"], "Pizza", "misleading", "neutral"),
    # --- out-of-set: must return None ---
    ("Seoul BBQ House", ["Korean BBQ Restaurant"], None, "explicit", "encodes"),
    ("Moonhan", ["Korean Restaurant", "BBQ Joint"], None, "misleading", "neutral"),
    ("Sushi Zen", ["Sushi Restaurant"], None, "explicit", "encodes"),
    ("Sticks'n'Sushi", ["Sushi Restaurant", "Japanese Restaurant"], None, "explicit", "encodes"),
    ("Le Petit Coin", ["French Restaurant"], None, "explicit", "neutral"),
    ("Bistro Margaux", ["French Restaurant"], None, "explicit", "neutral"),
    ("Bergmann Haus", ["German Restaurant"], None, "explicit", "neutral"),
    ("Alt-Berliner Biersalon", ["German Restaurant", "Beer Garden"], None, "explicit", "neutral"),
    ("Delhi Spice", ["Indian Restaurant"], None, "explicit", "encodes"),
    ("Curry Leaf", ["Indian Restaurant"], None, "explicit", "neutral"),
    ("Pho Saigon", ["Vietnamese Restaurant"], None, "explicit", "encodes"),
    ("The Anchor", ["Seafood Restaurant"], None, "generic", "neutral"),
    ("Athena Greek Taverna", ["Greek Restaurant"], None, "explicit", "encodes"),
    ("Habesha", ["Ethiopian Restaurant"], None, "explicit", "neutral"),
    ("Green Table", ["Vegan Restaurant"], None, "explicit", "neutral"),
    ("Dim Sum Palace", ["Chinese Restaurant", "Dim Sum Restaurant"], None, "explicit", "encodes"),
]

PREF = ["Ramen", "Mexican", "Thai", "Burger", "American", "Pizza"]


def main() -> int:
    if os.environ.get("CONCIERGE_CHROMA") != "1":
        print("Set CONCIERGE_CHROMA=1 (+ HF_HUB_OFFLINE=1 and cert env) and a running "
              "Chroma container to stress-test the vector classifier.")
        return 0
    from arrival_agent.web import chroma_store as cs

    rows = []
    for name, cats, truth, clarity, style in DATA:
        pred, score = cs.classify_cuisine(name, cats, PREF)
        if truth is not None:                    # in-set
            outcome = "correct" if pred == truth else ("false_reject" if pred is None else "wrong")
        else:                                    # out-of-set
            outcome = "correct" if pred is None else "false_match"
        rows.append((name, cats[0], truth, pred, score, outcome, clarity, style))

    inset = [r for r in rows if r[2] is not None]
    outset = [r for r in rows if r[2] is None]
    n_in, n_out = len(inset), len(outset)

    def rate(sub, key):
        return sum(1 for r in sub if r[5] == key)

    print(f"IN-SET (n={n_in})  should confidently match")
    print(f"  correct        {rate(inset,'correct')}/{n_in}  ({rate(inset,'correct')/n_in:.0%})")
    print(f"  false-reject   {rate(inset,'false_reject')}/{n_in}  (→None; recall cost)")
    print(f"  WRONG cuisine  {rate(inset,'wrong')}/{n_in}  (misclassified in-set)")
    print(f"\nOUT-OF-SET (n={n_out})  should return None")
    print(f"  correct-reject {rate(outset,'correct')}/{n_out}  ({rate(outset,'correct')/n_out:.0%})")
    print(f"  FALSE-MATCH    {rate(outset,'false_match')}/{n_out}  (dangerous — false taste badge)")

    print("\nby category clarity (in-set correct-match rate):")
    byc = defaultdict(lambda: [0, 0])
    for r in inset:
        byc[r[6]][1] += 1
        byc[r[6]][0] += (r[5] == "correct")
    for c, (ok, tot) in sorted(byc.items()):
        print(f"  {c:12} {ok}/{tot}")

    misses = [r for r in rows if r[5] in ("false_reject", "wrong", "false_match")]
    if misses:
        print("\nmisses (name · category · truth → pred @score · outcome):")
        for name, cat, truth, pred, score, outcome, _, _ in misses:
            print(f"  {name:22} {cat:22} {str(truth):8} → {str(pred):8} @{score}  {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
