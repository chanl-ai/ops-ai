"""How many database connections each request checks out, for the tables that hold a route to one transaction."""

from __future__ import annotations

import asyncio
from typing import Any

from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.pool import Pool

Request = tuple[str, str, dict[str, Any] | None, dict[str, str]]


async def connections(c: AsyncClient, requests: list[Request]) -> list[tuple[str, str, int, int]]:
    """Each request's status and how many connections it checked out. One: the route answers in the request
    transaction. More: it calls another party, so each read takes and returns its own and none is held meanwhile."""
    request_task = asyncio.current_task()
    counted: list[int] = []

    def checked_out(*_: object) -> None:
        # The app's loops check out connections too; only the request's own task counts.
        if asyncio.current_task() is request_task:
            counted[-1] += 1

    event.listen(Pool, "checkout", checked_out)
    seen: list[tuple[str, str, int, int]] = []
    try:
        for method, path, body, who in requests:
            counted.append(0)
            r = await c.request(method, path, json=body, headers=who)
            seen.append((method, path, r.status_code, counted[-1]))
    finally:
        event.remove(Pool, "checkout", checked_out)
    return seen
