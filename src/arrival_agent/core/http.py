"""Thin HTTP helper.

Tools call `get_json` instead of httpx directly so tests can stub one function
(`arrival_agent.core.http.get_json`) rather than mock the whole httpx surface.
Keeps real-network code out of the unit tests entirely.
"""

from __future__ import annotations

import os

import httpx

_DEFAULT_TIMEOUT = 10.0


class HttpError(RuntimeError):
    """A non-2xx response or a transport failure from an external API."""


def _verify():
    """CA verification setting for outbound TLS.

    Honors SSL_CERT_FILE / REQUESTS_CA_BUNDLE if set and present — this lets a
    machine behind a TLS-intercepting proxy (e.g. corporate AV that re-signs
    HTTPS with its own root) point at a bundle that includes that root. On a
    clean host (CI, Fly.io deploy) the env var is unset and we fall back to the
    default trust store. Never disables verification.
    """
    bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if bundle and os.path.exists(bundle):
        return bundle
    return True


def get_json(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict:
    """GET `url` and return parsed JSON. Raises HttpError on any failure."""
    try:
        resp = httpx.get(
            url, params=params, headers=headers, timeout=timeout, verify=_verify()
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300] if e.response is not None else ""
        raise HttpError(f"{url} returned {e.response.status_code}: {body}") from e
    except httpx.HTTPError as e:
        raise HttpError(f"{url} request failed: {e}") from e
