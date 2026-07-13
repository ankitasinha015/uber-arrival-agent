"""Eval: booking-email -> itinerary extraction.

Field-level accuracy over a small dataset of booking emails in different formats.
Offline runs the deterministic parser (use_llm=False); the point of an eval is
to SURFACE where it breaks — the variant email uses a phrasing the parser wasn't
built for, so accuracy drops and the eval catches it (that's exactly the gap the
LLM path, run with EVAL_LIVE=1, is meant to close).
"""

from __future__ import annotations

from arrival_agent.core.domain.itinerary import extract_itinerary, sample_booking_email

FIELDS = ["flight_no", "airport", "hotel", "scheduled_arrival"]

# A harder second format: "Route: ... ->" and "Accommodation:" instead of "hotel:".
_VARIANT_EMAIL = (
    "From: Delta <no-reply@delta.com>\n"
    "Subject: Confirmation — DL 288 to Los Angeles\n\n"
    "Flight: Delta DL 288\n"
    "Route: JFK (New York) -> Los Angeles (LAX)\n"
    "Fri, Jun 12 - arrives 10:40 PM\n"
    "Accommodation: The Line Hotel, Los Angeles\n"
)

CASES = [
    {
        "name": "canonical",
        "email": sample_booking_email(),
        "expected": {
            "flight_no": "UA 517", "airport": "SFO",
            "hotel": "Hotel Zephyr, San Francisco",
            "scheduled_arrival": "2026-05-20T23:15:00-07:00",
        },
    },
    {
        "name": "variant-format",
        "email": _VARIANT_EMAIL,
        "expected": {
            "flight_no": "DL 288", "airport": "LAX",
            "hotel": "The Line Hotel, Los Angeles",
            "scheduled_arrival": "2026-06-12T22:40:00-07:00",
        },
    },
]


def run_extraction_eval(use_llm: bool = False) -> list[dict]:
    rows = []
    for c in CASES:
        got = extract_itinerary(c["email"], use_llm=use_llm)
        hits = {f: (got.get(f) == c["expected"][f]) for f in FIELDS}
        rows.append({
            "case": c["name"],
            "hits": hits,
            "accuracy": sum(hits.values()) / len(hits),
            "misses": [f for f, ok in hits.items() if not ok],
        })
    return rows
