"""Tool: get_eats_options — REAL (Yelp Fusion API).

Returns restaurants near the hotel that are actually open at the target delivery
time, with category tags used for taste matching. Free tier; key in YELP_API_KEY.
https://docs.developer.yelp.com/docs/fusion-intro

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

    Taste matching = simple overlap of `cuisines` with Yelp category tags. No vector
    DB — category tags plus a preference filter cover this.

    Returns (shape TODO): name, location, categories, hours, est_prep_minutes, url.
    """
    raise NotImplementedError
