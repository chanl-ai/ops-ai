"""Tokens a connection holds (c-330): two calls finding a token past its time refresh it once, and a rotated refresh
token replaces the spent one in the same transaction."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_policy import AesGcmCipher
from ops_service_kit.settings import Settings
from ops_tools.auth.tokens import Tokens
from ops_tools.store.connections import ConnectionStore

SETTINGS = {"tokenUrl": "https://login.bank.test/token", "clientId": "ops-console"}


class AnyUrl:
    async def check_url(self, tenant_id: str, url: str) -> str:
        return "login.bank.test"


def _system(seen: list[dict[str, str]]) -> httpx.AsyncClient:
    """A token endpoint that rotates the refresh token on every refresh and takes a moment to answer."""

    async def answer(request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        seen.append(form)
        await asyncio.sleep(0.2)
        n = len(seen)
        return httpx.Response(200, json={"access_token": f"at-{n}", "refresh_token": f"rt-{n}", "expires_in": 3600})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


async def _connection(store: ConnectionStore, tenant: str) -> str:
    now = datetime.now(UTC)
    row = {
        "tenant_id": tenant,
        "id": "con_tok",
        "team_id": "team_platform",
        "name": "CRM",
        "auth_kind": "oauth2_auth_code",
        "available_to": None,
        "status": "healthy",
        "revision": 1,
        "created_by": "t",
        "created_at": now,
        "updated_by": "t",
        "updated_at": now,
    }
    assert await store.create(row, actor="t", at=now)
    return "con_tok"


async def test_two_calls_past_the_token_refresh_it_once(engine: AsyncEngine, tenant: str) -> None:
    store = ConnectionStore(engine)
    conn = await _connection(store, tenant)
    seen: list[dict[str, str]] = []
    cipher = AesGcmCipher(Settings().secrets_key.get_secret_value())
    tokens = Tokens(store, cipher, _system(seen), AnyUrl())  # pyright: ignore[reportArgumentType]
    # A sign-in whose token is already inside the refresh window.
    await tokens.store_answer(tenant, conn, "test", {"access_token": "at-0", "refresh_token": "rt-0", "expires_in": 5})
    both = await asyncio.gather(
        tokens.access(tenant, conn, "test", SETTINGS, None, grant="none"),
        tokens.access(tenant, conn, "test", SETTINGS, None, grant="none"),
    )
    assert [s["grant_type"] for s in seen] == ["refresh_token"], seen
    assert seen[0]["refresh_token"] == "rt-0"
    assert {t.access for t in both} == {"at-1"}
    # The rotated refresh token is the one held now: the next refresh spends rt-1, never rt-0 again.
    stale = both[0].rotation
    await tokens.access(tenant, conn, "test", SETTINGS, None, grant="none", stale_rotation=stale)
    assert [s.get("refresh_token") for s in seen] == ["rt-0", "rt-1"]
    row = await store.token(tenant, conn, "test")
    assert row is not None and "rt-" not in json.dumps({k: str(v) for k, v in row.items()})


async def test_a_refresh_after_a_401_replaces_only_the_refused_token(engine: AsyncEngine, tenant: str) -> None:
    """Two calls refused with the same token: the first refreshes it, the second finds the new one and sends it."""
    store = ConnectionStore(engine)
    conn = await _connection(store, tenant)
    seen: list[dict[str, str]] = []
    cipher = AesGcmCipher(Settings().secrets_key.get_secret_value())
    tokens = Tokens(store, cipher, _system(seen), AnyUrl())  # pyright: ignore[reportArgumentType]
    held = await tokens.store_answer(
        tenant, conn, "test", {"access_token": "at-0", "refresh_token": "rt-0", "expires_in": 3600}
    )
    refused_with: Any = held.rotation
    both = await asyncio.gather(
        tokens.access(tenant, conn, "test", SETTINGS, None, grant="none", stale_rotation=refused_with),
        tokens.access(tenant, conn, "test", SETTINGS, None, grant="none", stale_rotation=refused_with),
    )
    assert len(seen) == 1 and {t.access for t in both} == {"at-1"}
