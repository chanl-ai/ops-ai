"""tools-service's health, by failure mode: a health that says ok while the database is unreachable, so the stack treats
the gateway as up when every call would fail to be logged."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from .conftest import build_app


async def test_health_is_degraded_when_the_database_cannot_be_reached(seed: dict[str, Any]) -> None:
    dead = create_async_engine("postgresql+asyncpg://ops:ops@127.0.0.1:1/none")
    app = build_app(dead, seed, "t_unreached")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        r = await c.get("/health")
    await dead.dispose()
    assert (r.status_code, r.json()) == (503, {"status": "degraded", "reason": "database"})
