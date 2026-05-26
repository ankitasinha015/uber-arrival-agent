"""Live API smoke tests — SKIPPED by default.

These hit the real Mapbox + Foursquare APIs to validate keys and response
shapes. They cost a few free-tier calls and need network + real keys, so they
are gated behind LIVE_API_TESTS=1 and never run in normal CI.

Run locally with:
    LIVE_API_TESTS=1 SSL_CERT_FILE=<ca-bundle> PYTHONPATH=src pytest tests/test_tools_live.py

(SSL_CERT_FILE is only needed on a machine behind a TLS-intercepting proxy.)
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("LIVE_API_TESTS") != "1",
    reason="live API tests are opt-in (set LIVE_API_TESTS=1)",
)

_HOTEL = "Marriott Marquis San Francisco, CA"


def test_mapbox_geocode_live():
    from arrival_agent.core.tools.eta import geocode

    lat, lng = geocode(_HOTEL)
    # San Francisco is roughly 37.7N, -122.4W.
    assert 37.0 < lat < 38.5
    assert -123.5 < lng < -122.0


def test_mapbox_eta_live():
    from arrival_agent.core.tools.eta import estimate_eta

    mins = estimate_eta("San Francisco International Airport", _HOTEL)
    # SFO -> downtown SF is realistically 10-45 min depending on traffic.
    assert 5 < mins < 90


def test_foursquare_search_live():
    from arrival_agent.core.tools.restaurants import get_eats_options

    results = get_eats_options(_HOTEL, limit=3)
    assert results, "expected at least one restaurant near a downtown hotel"
    first = results[0]
    assert first["restaurant_name"]
    assert isinstance(first["categories"], list)
    assert first["restaurant_id"]
