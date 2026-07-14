"""Generate a synthetic trace set for error analysis (evals-skills methodology).

Real trip data doesn't exist, so we generate diverse, failure-targeting inputs and
run them through the agent's two judgment surfaces, capturing full traces:

  A) EXTRACTION  booking email -> itinerary. Dimension = email FORMAT, chosen to
     stress each regex anchor in the deterministic parser (->, hotel:, AM/PM, Mon DD).
  B) RANKING     hotel location -> live restaurants -> order-pattern suggestion.
     Dimensions = taste-profile shape x city (cuisine availability, incl. international).

Output: evals/synthetic/extraction_traces.jsonl + ranking_traces.jsonl, each row a
full trace (input, ground truth / context, output, and where it broke) for review.

Run:  python -m evals.gen_synthetic          (extraction offline)
      python -m evals.gen_synthetic --live   (+ ranking, needs geo API keys)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from arrival_agent.core import config  # noqa: F401 — loads .env
from arrival_agent.core.domain.itinerary import extract_itinerary

_OUT = Path(__file__).resolve().parent / "synthetic"
_OUT.mkdir(exist_ok=True)
_PAC = timezone(timedelta(hours=-7))
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# --- base trips (real airlines / airports / hotels) -----------------------------
_TRIPS = [
    {"airline": "United Airlines", "fno": "UA 517", "oc": "Newark", "ocode": "EWR",
     "dc": "San Francisco", "dcode": "SFO", "hotel": "Hotel Zephyr, San Francisco",
     "mon": 5, "day": 20, "h": 11, "m": 15, "ap": "PM"},
    {"airline": "Delta", "fno": "DL 288", "oc": "New York", "ocode": "JFK",
     "dc": "Los Angeles", "dcode": "LAX", "hotel": "The Line Hotel, Los Angeles",
     "mon": 6, "day": 12, "h": 10, "m": 40, "ap": "PM"},
    {"airline": "Lufthansa", "fno": "LH 435", "oc": "New York", "ocode": "JFK",
     "dc": "Berlin", "dcode": "BER", "hotel": "Hotel Zoo, Berlin",
     "mon": 7, "day": 3, "h": 11, "m": 5, "ap": "PM"},
    {"airline": "American", "fno": "AA 118", "oc": "New York", "ocode": "JFK",
     "dc": "Chicago", "dcode": "ORD", "hotel": "The Langham, Chicago",
     "mon": 8, "day": 9, "h": 12, "m": 30, "ap": "AM"},
]


def _hour24(t):
    h, ap = t["h"], t["ap"]
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return h


def _expected(t):
    return {
        "flight_no": t["fno"], "airport": t["dcode"], "hotel": t["hotel"],
        "scheduled_arrival": datetime(2026, t["mon"], t["day"], _hour24(t), t["m"], tzinfo=_PAC).isoformat(),
    }


# --- email format renderers (the failure-targeting dimension) -------------------
def f_canonical(t):
    return (f"From: {t['airline']} <no-reply>\nSubject: Your trip — {t['fno']} to {t['dc']}\n\n"
            f"  {t['airline']} {t['fno']}\n"
            f"  {t['oc']} ({t['ocode']}) -> {t['dc']} ({t['dcode']})\n"
            f"  Wed, {_MON[t['mon']-1]} {t['day']} - departs 8:05 PM - arrives {t['h']}:{t['m']:02d} {t['ap']}\n\n"
            f"hotel:\n  {t['hotel']}\n")


def f_arrow_unicode(t):  # '→' instead of '->' — breaks the airport regex
    return f_canonical(t).replace("->", "→")


def f_accommodation(t):  # 'Accommodation:' instead of 'hotel:' — breaks the hotel regex
    return (f"From: {t['airline']}\nSubject: Confirmation — {t['fno']} to {t['dc']}\n\n"
            f"Flight: {t['airline']} {t['fno']}\n"
            f"Route: {t['oc']} ({t['ocode']}) -> {t['dc']} ({t['dcode']})\n"
            f"Wed, {_MON[t['mon']-1]} {t['day']} - arrives {t['h']}:{t['m']:02d} {t['ap']}\n"
            f"Accommodation: {t['hotel']}\n")


def f_time24(t):  # 24h clock, no AM/PM — breaks the arrival-time regex
    return (f"From: {t['airline']}\nSubject: {t['fno']}\n\n  {t['airline']} {t['fno']}\n"
            f"  {t['oc']} ({t['ocode']}) -> {t['dc']} ({t['dcode']})\n"
            f"  {_MON[t['mon']-1]} {t['day']} - arrives {_hour24(t):02d}:{t['m']:02d}\n\n"
            f"hotel:\n  {t['hotel']}\n")


def f_numeric_date(t):  # 'MM/DD' instead of 'Mon DD' — breaks the date regex
    return (f"From: {t['airline']}\nSubject: {t['fno']}\n\n  {t['airline']} {t['fno']}\n"
            f"  {t['oc']} ({t['ocode']}) -> {t['dc']} ({t['dcode']})\n"
            f"  {t['mon']:02d}/{t['day']:02d}/2026 - arrives {t['h']}:{t['m']:02d} {t['ap']}\n\n"
            f"hotel:\n  {t['hotel']}\n")


def f_terse(t):  # SMS-style codes — stresses several regexes at once
    fno = t["fno"].replace(" ", "")
    return (f"{t['airline'][:2].upper()} booking\n{fno} {t['ocode']}-{t['dcode']} "
            f"{t['day']}{_MON[t['mon']-1].upper()} arr {_hour24(t):02d}{t['m']:02d}\n{t['hotel']}\n")


def f_inline_hotel(t):  # hotel in prose, not a labelled block
    return (f"From: {t['airline']}\nSubject: {t['fno']} to {t['dc']}\n\n"
            f"  {t['airline']} {t['fno']}\n"
            f"  {t['oc']} ({t['ocode']}) -> {t['dc']} ({t['dcode']})\n"
            f"  Wed, {_MON[t['mon']-1]} {t['day']} - arrives {t['h']}:{t['m']:02d} {t['ap']}\n\n"
            f"You're staying at {t['hotel']} — check-in from 3 PM.\n")


_FORMATS = [("canonical", f_canonical), ("arrow-unicode", f_arrow_unicode),
            ("accommodation-label", f_accommodation), ("24h-time", f_time24),
            ("numeric-date", f_numeric_date), ("terse-codes", f_terse),
            ("inline-hotel", f_inline_hotel)]
_FIELDS = ["flight_no", "airport", "hotel", "scheduled_arrival"]


def gen_extraction():
    rows = []
    for t in _TRIPS:
        exp = _expected(t)
        for fmt_name, render in _FORMATS:
            email = render(t)
            got = extract_itinerary(email, use_llm=False)
            hits = {f: (got.get(f) == exp[f]) for f in _FIELDS}
            rows.append({
                "id": f"{t['fno'].replace(' ', '')}-{fmt_name}",
                "surface": "extraction", "format": fmt_name, "route": f"{t['ocode']}->{t['dcode']}",
                "email": email, "expected": exp, "got": got,
                "misses": [f for f, ok in hits.items() if not ok],
                "accuracy": sum(hits.values()) / len(hits),
            })
    (_OUT / "extraction_traces.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return rows


# --- ranking traces (live geo) --------------------------------------------------
_TASTES = {
    "mexican-dominant": ["Mexican", "Thai", "American", "Pizza", "Burger", "Ramen"],
    "ramen-niche":      ["Ramen", "Thai", "Mexican", "Burger", "American", "Pizza"],
    "burger-common":    ["Burger", "American", "Pizza", "Mexican", "Thai", "Ramen"],
}
_HOTELS = [
    ("New York", "The New Yorker Hotel, 481 8th Ave, New York, NY 10001", "$"),
    ("Berlin (intl)", "Hotel Zoo Berlin, Kurfürstendamm 25, 10719 Berlin, Germany", "€"),
    ("Los Angeles", "The LINE Hotel, 3515 Wilshire Blvd, Los Angeles, CA 90010", "$"),
    ("San Francisco", "Hotel Zephyr, 250 Beach St, San Francisco, CA 94133", "$"),
]


def gen_ranking():
    from arrival_agent.web import concierge as C
    rows = []
    for taste_name, taste in _TASTES.items():
        for city, addr, cur in _HOTELS:
            ctx = {"hotel_address": addr, "pref": taste, "city": f"Hotel, {city}",
                   "currency": cur, "deliver_at": C._DELIVER, "traveler_id": None}
            cands = C._arrival_find(ctx)
            cs = C._arrival_design(cands, ctx)
            rows.append({
                "id": f"{taste_name}@{city}", "surface": "ranking",
                "taste_profile": taste_name, "taste": taste, "city": city,
                "nearby_sample": [f"{c['restaurant_name']} [{', '.join(c.get('categories', [])[:1])}]"
                                  for c in cands[:6]],
                "top1_cuisine_overall": taste[0],
                "options": [{"name": o.restaurant_name, "cuisine": (o.cuisine_tags or [""])[0],
                             "why": o.why_this_one, "badge": o.badge, "dish": o.items[0]}
                            for o in cs.options],
            })
    (_OUT / "ranking_traces.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return rows


# Compared on the unambiguous fields only. scheduled_arrival is excluded: the parser
# hardcodes 2026/Pacific while the LLM *infers* year + timezone, so a correctly-read
# time differs in representation — not a fair cross-path comparison.
_CMP_FIELDS = ["flight_no", "airport", "hotel"]


def compare_extraction_paths():
    """Each synthetic email through BOTH the parser and the LLM path; per-format
    accuracy on the unambiguous fields (flight_no / airport / hotel)."""
    def _acc(got, exp):
        return sum(got.get(f) == exp[f] for f in _CMP_FIELDS) / len(_CMP_FIELDS)

    agg = {}
    for t in _TRIPS:
        exp = _expected(t)
        for fmt_name, render in _FORMATS:
            email = render(t)
            p = _acc(extract_itinerary(email, use_llm=False), exp)
            l = _acc(extract_itinerary(email, use_llm=True), exp)  # live LLM
            agg.setdefault(fmt_name, {"p": [], "l": []})
            agg[fmt_name]["p"].append(p)
            agg[fmt_name]["l"].append(l)
    return agg


def main():
    live = "--live" in sys.argv
    if "--llm-ext" in sys.argv:
        print("EXTRACTION: parser vs LLM path, per format (flight/airport/hotel)")
        agg = compare_extraction_paths()
        for fmt, d in agg.items():
            p = sum(d["p"]) / len(d["p"]); l = sum(d["l"]) / len(d["l"])
            print(f"   {fmt:20} parser {p:.0%}  →  LLM {l:.0%}   ({'+' if l>=p else ''}{(l-p):.0%})")
        return
    ext = gen_extraction()
    print(f"EXTRACTION: {len(ext)} traces -> evals/synthetic/extraction_traces.jsonl")
    by_fmt = {}
    for r in ext:
        by_fmt.setdefault(r["format"], []).append(r["accuracy"])
    for fmt, accs in by_fmt.items():
        print(f"   {fmt:20} mean acc {sum(accs)/len(accs):.0%}")
    if live:
        rank = gen_ranking()
        print(f"\nRANKING: {len(rank)} traces -> evals/synthetic/ranking_traces.jsonl")
    else:
        print("\nRANKING: skipped — pass --live (needs geo keys)")


if __name__ == "__main__":
    main()
