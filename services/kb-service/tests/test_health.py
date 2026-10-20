"""kb-service's health, by failure mode: a health that says ok while the database is unreachable, so the stack and
chat treat knowledge as available when every query would fail."""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from ops_kb.app import create_kb_app


async def test_health_is_ok_on_a_reachable_database(client: httpx.AsyncClient) -> None:
    r = await client.get("/health")
    assert (r.status_code, r.json()) == (200, {"status": "ok"})


async def test_health_is_degraded_when_the_database_cannot_be_reached() -> None:
    dead = create_async_engine("postgresql+asyncpg://ops:ops@127.0.0.1:1/none")
    app = create_kb_app(dead)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kb") as c:
        r = await c.get("/health")
    await dead.dispose()
    assert (r.status_code, r.json()) == (503, {"status": "degraded", "reason": "database"})


async def test_console_preflight_is_answered(client: httpx.AsyncClient) -> None:
    """A browser on the console origin preflights every call; a refused preflight breaks every knowledge page."""
    r = await client.options(
        "/v1/knowledge-bases",
        headers={
            "Origin": "http://localhost:3016",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-team-id",
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3016"
