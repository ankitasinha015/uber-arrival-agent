"""Configuration — loads .env and exposes API keys + tunables.

Keys live in .env (gitignored). This module is the single place that reads them,
so the rest of the codebase never touches os.environ directly. A missing key
raises a clear, actionable error instead of a confusing 401 later.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

# Load .env from the current working directory / nearest parent. Idempotent.
load_dotenv()


class MissingKey(RuntimeError):
    """Raised when a required API key is absent from the environment."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingKey(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


@lru_cache
def foursquare_key() -> str:
    return _require("FOURSQUARE_API_KEY")


@lru_cache
def mapbox_token() -> str:
    return _require("MAPS_API_KEY")


@lru_cache
def anthropic_key() -> str:
    return _require("ANTHROPIC_API_KEY")


# Foursquare Places API is date-versioned via the X-Places-Api-Version header.
FOURSQUARE_API_VERSION = "2025-06-17"
