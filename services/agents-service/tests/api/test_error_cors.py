"""An unexpected error reaches the console as the 500 envelope with CORS headers. Without them the browser reports a
CORS failure and the page never sees the status or the envelope."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from ops_agents.api.routers import engine
from ops_service_kit.settings import Settings

# The console origin the app allows, read as the client fixture's app reads it (a lane's console is on its own port).
CONSOLE = Settings(database_url="sqlite+aiosqlite://").cors_origins[0]


async def test_a_500_to_the_console_origin_carries_cors_headers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_: object) -> object:
        raise RuntimeError("store is down")

    monkeypatch.setattr(engine, "definitions", broken)
    res = await client.get("/v1/workflows/definitions", headers={"Origin": CONSOLE})
    assert res.status_code == 500
    assert res.headers.get("access-control-allow-origin") == CONSOLE
    assert res.json()["error"]["code"] == "internal"
