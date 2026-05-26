"""Tool: get_eats_options — REAL (Foursquare Places API).

Returns restaurants near the hotel that are actually open at the target delivery
time, with category tags used for taste matching. Free tier; Service Key in
FOURSQUARE_API_KEY.

New Foursquare Places API:
  - Base: https://places-api.foursquare.com
  - Auth: Authorization: Bearer <FOURSQUARE_API_KEY>
  - Header: X-Places-Api-Version: <date version, e.g. 2025-06-17>
  - Place Search for nearby restaurants; Place Details for opening hours.
  https://location.foursquare.com/developer/

The provider is intentionally behind this thin tool. Nothing downstream
(domain logic, adapters, taste store) knows it's Foursquare — swapping
providers means editing only this file.

Implementation: TODO.
"""

from __future__ import annotations

from datetime import datetime


def get_eats_options(
    near: str,
    open_at: datetime,
    cuisines: list[str] | None = None,
    max_price: int | None = None,
) -> list[dict]:
    """Find open restaurants near `near` at `open_at`, ranked by taste match.

    Taste matching: the envelope filter (cuisines, price) runs first on
    Foursquare category tags; the Chroma taste store (core/domain/taste.py)
    re-ranks within the filtered set by similarity to the user's well-rated
    past picks. No-history users fall back to category overlap + rating.

    Returns (shape TODO): name, location, categories, hours, est_prep_minutes, url.
    """
    raise NotImplementedError
