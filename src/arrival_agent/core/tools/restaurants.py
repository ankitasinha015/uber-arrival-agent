"""Tool: get_eats_options — REAL (Foursquare Places API).

Returns restaurants near the hotel, normalized to a flat dict shape the domain
logic consumes. Foursquare's category tags feed the envelope filter; the Chroma
taste store (core/domain/taste.py) re-ranks within the filtered set.

New Foursquare Places API:
  - Base:    https://places-api.foursquare.com/places/search
  - Auth:    Authorization: Bearer <FOURSQUARE_API_KEY>
  - Version: X-Places-Api-Version header (see config.FOURSQUARE_API_VERSION)

The hotel arrives as a text address; we geocode it via Mapbox (eta.geocode) and
pass coords to Foursquare. The provider is intentionally swappable behind this
tool — nothing downstream knows it's Foursquare.

NOTE: the exact Foursquare response field names are validated against a live
call during step 2 and `_normalize` is adjusted to match reality. Parsing is
defensive (`.get` everywhere) so a missing optional field degrades gracefully.
"""

from __future__ import annotations

from datetime import datetime

from arrival_agent.core.config import FOURSQUARE_API_VERSION, foursquare_key
from arrival_agent.core.http import get_json
from arrival_agent.core.metrics import instrumented
from arrival_agent.core.tools.eta import geocode

_SEARCH_URL = "https://places-api.foursquare.com/places/search"
# Foursquare taxonomy: "Dining and Drinking" top-level category.
_RESTAURANT_CATEGORY = "4d4b7105d754a06374d81259"


def _normalize(place: dict) -> dict:
    """Flatten a Foursquare place into the shape the domain logic expects."""
    categories = [c.get("name", "") for c in place.get("categories", [])]
    loc = place.get("location", {})
    return {
        "restaurant_id": place.get("fsq_place_id") or place.get("fsq_id", ""),
        "restaurant_name": place.get("name", ""),
        "categories": categories,
        "address": loc.get("formatted_address", ""),
        "distance_m": place.get("distance"),
        # hours + price are fetched per-place via Place Details if needed;
        # search returns them inconsistently. est_prep_minutes is a downstream
        # heuristic, not from Foursquare.
        "raw": place,
    }


@instrumented("get_eats_options")
def get_eats_options(
    near: str,
    open_at: datetime | None = None,
    cuisines: list[str] | None = None,
    max_price: int | None = None,
    limit: int = 10,
) -> list[dict]:
    """Find restaurants near `near`, nearest first.

    `cuisines` / `max_price` are applied as the envelope filter by the caller
    (domain logic), not here — this tool returns raw candidates. `open_at` is
    passed through to Foursquare when supported.

    Returns a list of normalized dicts (see `_normalize`).
    """
    lat, lng = geocode(near)
    headers = {
        "Authorization": f"Bearer {foursquare_key()}",
        "X-Places-Api-Version": FOURSQUARE_API_VERSION,
        "accept": "application/json",
    }
    params: dict = {
        "ll": f"{lat},{lng}",
        "fsq_category_ids": _RESTAURANT_CATEGORY,
        "radius": 4000,
        "limit": limit,
        "sort": "DISTANCE",
    }
    data = get_json(_SEARCH_URL, params=params, headers=headers)
    results = data.get("results", data.get("places", []))
    return [_normalize(p) for p in results]
