"""Tools: geocode + estimate_eta — REAL (Mapbox).

`geocode` turns a place string ("Marriott Union Square, San Francisco") into
(lat, lng) via the Mapbox Geocoding API. `estimate_eta` geocodes both endpoints
and asks the Mapbox Directions API for driving time.

Mapbox token in MAPS_API_KEY. Geocoding + Directions are both on the free tier.

The provider is intentionally behind these tools — nothing downstream knows it's
Mapbox.
"""

from __future__ import annotations

from urllib.parse import quote

from arrival_agent.core.config import mapbox_token
from arrival_agent.core.http import get_json
from arrival_agent.core.metrics import instrumented

_GEOCODE_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places/{q}.json"
_DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving/{coords}"


@instrumented("geocode")
def geocode(place: str, proximity: tuple[float, float] | None = None) -> tuple[float, float]:
    """Return (lat, lng) for a place string. Raises LookupError if not found.

    `proximity` (lat, lng) biases results toward a location — important for
    short/ambiguous queries like an airport name, which can otherwise match a
    same-named place on the other side of the world.
    """
    url = _GEOCODE_URL.format(q=quote(place))
    params: dict = {"access_token": mapbox_token(), "limit": 1}
    if proximity is not None:
        p_lat, p_lng = proximity
        params["proximity"] = f"{p_lng},{p_lat}"  # Mapbox wants lng,lat
    data = get_json(url, params=params)
    features = data.get("features", [])
    if not features:
        raise LookupError(f"could not geocode: {place!r}")
    lng, lat = features[0]["center"]  # Mapbox returns [lng, lat]
    return (lat, lng)


@instrumented("estimate_eta")
def estimate_eta(origin: str, destination: str) -> int:
    """Driving minutes from `origin` to `destination` with current conditions.

    Both args are place strings; they're geocoded first. The destination is
    geocoded first, then the origin is geocoded with the destination as a
    proximity hint — so an ambiguous origin like "SFO" resolves to the airport
    near the destination, not a same-named place elsewhere. Returns whole
    minutes. Raises LookupError if no route exists.
    """
    d_lat, d_lng = geocode(destination)
    o_lat, o_lng = geocode(origin, proximity=(d_lat, d_lng))
    coords = f"{o_lng},{o_lat};{d_lng},{d_lat}"
    url = _DIRECTIONS_URL.format(coords=coords)
    data = get_json(
        url,
        params={"access_token": mapbox_token(), "overview": "false"},
    )
    routes = data.get("routes", [])
    if not routes:
        raise LookupError(f"no driving route from {origin!r} to {destination!r}")
    return round(routes[0]["duration"] / 60)
