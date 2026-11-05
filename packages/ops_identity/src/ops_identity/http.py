"""The calls `Identity` makes to platform-service, over HTTP: the public key set and, on the internal mount with this
service's service token, API-key introspection and the tenant's permission version."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import httpx

from .jwks import JwksFetch
from .resolve import CurrentVersion, Introspect


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


def http_current_version(client: httpx.AsyncClient, internal_url: str, token: Callable[[str], str]) -> CurrentVersion:
    """`internal_url` is platform-service's internal mount; `token` mints this service's token naming the tenant."""

    async def current(tenant_id: str) -> int | None:
        r = await client.get(
            f"{internal_url.rstrip('/')}/v1/permission-version", headers={"Authorization": f"Bearer {token(tenant_id)}"}
        )
        r.raise_for_status()
        return int(r.json()["data"]["permissionVersion"])

    return current
