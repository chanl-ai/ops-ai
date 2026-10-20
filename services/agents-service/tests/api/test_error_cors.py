"""An unexpected error reaches the console as the 500 envelope with CORS headers. Without them the browser reports a
CORS failure and the page never sees the status or the envelope."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from ops_agents.api.routers import engine

CONSOLE = "http://localhost:3016"


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
