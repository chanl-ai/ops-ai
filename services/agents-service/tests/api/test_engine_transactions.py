"""Each route that only reads and writes this service's rows holds one transaction: one connection checked out for the
whole request, so its reads agree with each other and its writes commit together."""

from __future__ import annotations

import asyncio

from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.pool import Pool

from .test_engine_definitions import named

# (method, path) for each route on the request transaction, after a draft `tx_flow` is saved.
ON_ONE_TRANSACTION = [
    ("get", "/v1/workflows/definitions"),
    ("get", "/v1/workflows/definitions/tx_flow"),
    ("get", "/v1/workflows/definitions/account-uses?app=mail&name=Inbox"),
    ("post", "/v1/workflows/definitions/tx_flow/archive"),
    ("post", "/v1/workflows/definitions/tx_flow/restore"),
    ("post", "/v1/workflows/definitions/tx_flow/pause"),
    ("post", "/v1/workflows/definitions/tx_flow/resume"),
    ("delete", "/v1/workflows/definitions/tx_flow"),
    ("get", "/v1/threads"),
    ("get", "/v1/graphs/tx_flow/versions"),
    ("get", "/v1/graphs"),
]


async def checkouts(
    client: AsyncClient, routes: list[tuple[str, str]], headers: dict[str, str] | None = None
) -> list[tuple[str, int, int]]:
    """(path, status, connections the request's own task checked out) for each route, called in order."""
    request_task = asyncio.current_task()
    counted: list[int] = []

    def checked_out(*_: object) -> None:
        # The app's loops check out connections too; only the request's own task counts.
        if asyncio.current_task() is request_task:
            counted[-1] += 1

    event.listen(Pool, "checkout", checked_out)
    seen: list[tuple[str, int, int]] = []
    try:
        for method, path in routes:
            counted.append(0)
            r = await client.request(method.upper(), path, headers=headers)
            seen.append((path, r.status_code, counted[-1]))
    finally:
        event.remove(Pool, "checkout", checked_out)
    return seen


async def test_each_store_only_route_checks_out_one_connection(client: AsyncClient) -> None:
    saved = await client.post("/v1/workflows/definitions", json={"definition": named("tx_flow", "Tx flow")})
    assert saved.status_code == 201, saved.text
    seen = await checkouts(client, ON_ONE_TRANSACTION)
    # pause and resume answer 409 on a draft (no live version), after their reads, still on one connection.
    assert [(p, n) for p, _, n in seen if n != 1] == [], seen
    assert all(code < 500 for _, code, _ in seen), seen
