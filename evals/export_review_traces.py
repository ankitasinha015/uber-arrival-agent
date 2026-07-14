"""Sample dinner choice-set traces and write them for the review interface.

Sampling logic lives HERE (outside the annotation app, per build-review-interface).
Each trace is one arrival-design decision: a traveler + hotel + the restaurants open
nearby → the ranked, badged, copy-written choice set the agent produced. A domain
expert labels the whole trace Pass/Fail: is this a good, HONEST dinner suggestion?

The candidate sets are handcrafted (deterministic, no live geo) and deliberately span
the judgment space: clean taste matches, honest abstains (Korean BBQ / German → shown
neutrally), weak fallbacks (nothing in-taste open nearby), and an international arrival.

Writes evals/review/traces.js as `window.TRACES = [...]` (a <script> tag, so the app
opens straight from file:// with no fetch/CORS).

Run: [CONCIERGE_CHROMA=1 HF_HUB_OFFLINE=1] python -m evals.export_review_traces
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from arrival_agent.web import concierge as C

# (label, traveler, hotel_city, [candidates]) — candidates: (name, [categories], dist_m)
SCENARIOS = [
    ("NYC · burger-lover · clean + honest abstains",
     {"name": "Dev Sharma", "taste": ["Burger", "American", "Pizza", "Mexican", "Thai", "Ramen"]},
     "The Standard, High Line, New York",
     [("Shake Shack", ["Burger Joint"], 300), ("Joe's Pizza", ["Pizzeria"], 550),
      ("Moonhan Korean BBQ", ["Korean BBQ Restaurant"], 240),
      ("Le Petit Coin", ["French Restaurant"], 700)]),
    ("Chicago · Thai/Ramen first-timer · in-taste match",
     {"name": "Priya Nair", "taste": ["Thai", "Ramen", "Mexican", "Burger", "American", "Pizza"]},
     "theWit, Chicago",
     [("Riverside Thai Kitchen", ["Thai Restaurant"], 400), ("Slurp Ramen", ["Ramen Restaurant"], 900),
      ("The Hatch", ["Diner"], 260), ("Nonna's Slice", ["Pizzeria"], 620)]),
    ("SF · American road-warrior · weak fallback (nothing in-taste near)",
     {"name": "Marcus Lee", "taste": ["American", "Burger", "Pizza", "Mexican", "Thai", "Ramen"]},
     "Hotel Zephyr, Pier 39, San Francisco",
     [("Sushi Zen", ["Sushi Restaurant"], 210), ("Athena Greek Taverna", ["Greek Restaurant"], 350),
      ("The Anchor", ["Seafood Restaurant"], 180), ("Blaze Pizza", ["Pizzeria"], 1200)]),
    ("Berlin · international arrival · mostly out-of-taste (honest labels)",
     {"name": "Lena Fischer", "taste": ["Pizza", "Mexican", "Thai", "Burger", "American", "Ramen"]},
     "Hotel Adlon Kempinski, Berlin",
     [("Alt-Berliner Biersalon", ["German Restaurant", "Beer Garden"], 300),
      ("Bergmann Haus", ["German Restaurant"], 500), ("Pho Saigon", ["Vietnamese Restaurant"], 640),
      ("Ristorante Roma", ["Italian Restaurant", "Pizzeria"], 820)]),
    ("LA · Mexican-lover · generic-category trap",
     {"name": "Tomás Rivera", "taste": ["Mexican", "Burger", "Pizza", "American", "Thai", "Ramen"]},
     "The Line Hotel, Koreatown, Los Angeles",
     [("El Farolito", ["Restaurant"], 260), ("Burrito Bros", ["Fast Food Restaurant"], 340),
      ("Shake Shack", ["Burger Joint"], 500), ("Seoul BBQ House", ["Korean BBQ Restaurant"], 150)]),
    ("NYC · pizza-lover · italian-vs-pizza edge",
     {"name": "Gia Conti", "taste": ["Pizza", "American", "Mexican", "Thai", "Burger", "Ramen"]},
     "Ace Hotel, New York",
     [("Roma Trattoria", ["Italian Restaurant"], 300), ("Joe's Pizza", ["Pizzeria"], 480),
      ("Keens Steakhouse", ["Steakhouse"], 350), ("American Pie", ["Pizzeria"], 900)]),
]


def _serialize(cs) -> dict:
    return {
        "lead": getattr(cs, "lead", ""),
        "axis": getattr(getattr(cs, "axis", None), "value", str(getattr(cs, "axis", ""))),
        "why_these": getattr(cs, "why_these", ""),
        "options": [{
            "restaurant_name": o.restaurant_name,
            "cuisine_label": (o.cuisine_tags or ["Restaurant"])[0],
            "badge": getattr(o, "badge", None),
            "why": o.why_this_one,
            "dish_pitch": getattr(o, "dish_pitch", ""),
            "items": list(o.items or []),
            "est_total": getattr(o, "est_total", None),
        } for o in cs.options],
    }


def build_traces() -> list[dict]:
    traces = []
    for i, (label, traveler, hotel, cands) in enumerate(SCENARIOS, 1):
        candidates = [{"restaurant_id": f"c{j}", "restaurant_name": n, "categories": cats,
                       "distance_m": d} for j, (n, cats, d) in enumerate(cands)]
        ctx = {"pref": traveler["taste"], "traveler_id": None,
               "city": hotel, "deliver_at": "01:15"}
        cs = C._arrival_design(candidates, ctx)
        traces.append({
            "id": f"trace-{i:02d}",
            "scenario": label,
            "traveler": traveler,
            "hotel": hotel,
            "candidates": [{"name": n, "categories": cats, "distance_m": d} for n, cats, d in cands],
            "output": _serialize(cs),
        })
    return traces


def main() -> int:
    traces = build_traces()
    out = Path(__file__).parent / "review" / "traces.js"
    out.parent.mkdir(exist_ok=True)
    out.write_text("window.TRACES = " + json.dumps(traces, indent=2) + ";\n", encoding="utf-8")
    mode = "Chroma classifier" if os.environ.get("CONCIERGE_CHROMA") == "1" else "regex-alias fallback"
    print(f"wrote {len(traces)} traces → {out}  ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
