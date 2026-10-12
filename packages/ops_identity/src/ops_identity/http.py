"""The two calls `Identity` makes to platform-service, over HTTP: the public key set and, on the internal mount,
API-key introspection with this service's service token."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import httpx

from .jwks import JwksFetch
from .resolve import Introspect


def http_jwks(client: httpx.AsyncClient, url: str) -> JwksFetch:
    async def fetch() -> dict[str, Any]:
        r = await client.get(url)
        r.raise_for_status()
        return cast(dict[str, Any], r.json())

    return fetch


def http_introspect(client: httpx.AsyncClient, url: str, token: str | Callable[[], str]) -> Introspect:
    """`token` is a service token, or a function minting a fresh one per call so none outlives its 60 seconds."""

    async def introspect(api_key: str) -> dict[str, Any] | None:
        bearer = token() if callable(token) else token
        r = await client.post(url, json={"apiKey": api_key}, headers={"Authorization": f"Bearer {bearer}"})
        if r.status_code == 401:
            return None
        r.raise_for_status()
        return cast(dict[str, Any], r.json()["data"])

    return introspect
