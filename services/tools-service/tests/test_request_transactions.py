"""How many transactions a request holds, by failure mode: a route opening one transaction per store call, so one
screen's read sees rows from different moments and a change can land without the row that goes with it. Each route
group adds its rows to ROUTES as it moves onto the request transaction (`Tx`)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.logging import captured_logging
from ops_service_kit.settings import Settings
from ops_store.database import open_database

from .test_egress_and_secrets_need_security_admin import client  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_review_decisions import person

# (method, path, body): each answered in one transaction.
ROUTES = [
    ("GET", "/v1/egress", None),
    ("GET", "/v1/egress/hosts", None),
    ("POST", "/v1/egress/hosts", {"value": "tx-count.example.com"}),
    ("POST", "/v1/egress/hosts/remove", {"value": "tx-count.example.com"}),
    ("POST", "/v1/egress/ranges", {"value": "10.71.0.0/16"}),
    ("POST", "/v1/egress/ranges/remove", {"value": "10.71.0.0/16"}),
]


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """The engine as the service opens it, which counts the request's transactions for its request line."""
    e = open_database(Settings().database_url)
    yield e
    await e.dispose()


async def test_each_route_answers_in_one_transaction(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    sam = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    counts: dict[str, int] = {}
    for method, path, body in ROUTES:
        r, counts[f"{method} {path}"] = await _counted(client, method, path, body, sam)
        assert r.status_code in (200, 201), (path, r.text)
    assert counts == {f"{m} {p}": 1 for m, p, _ in ROUTES}, counts


async def _counted(
    c: httpx.AsyncClient, method: str, path: str, body: object, headers: dict[str, str], **params: int | str
) -> tuple[httpx.Response, int]:
    """The answer and how many transactions the request held, from its request line."""
    with captured_logging("tools-tx") as stream:
        r = await c.request(method, path, json=body, headers=headers, params=params or None)
    line = next(json.loads(x) for x in stream.getvalue().splitlines() if '"http.request"' in x)
    return r, int(line["db.tx_count"])


@pytest.mark.parametrize("path", ["/v1/egress/hosts"])
async def test_a_page_past_the_end_answers_the_last_page(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
    path: str,
) -> None:
    sam = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    for i in range(3):
        added = await client.post(path, json={"value": f"past-end-{i}.example.com"}, headers=sam)
        assert added.status_code == 201, added.text
    r = await client.get(path, params={"search": "past-end-", "page": 9, "pageSize": 2}, headers=sam)
    assert r.status_code == 200, r.text
    page = r.json()["data"]
    assert [h["host"] for h in page["data"]] == ["past-end-2.example.com"]
    assert (page["pagination"]["page"], page["pagination"]["total"]) == (2, 3)
