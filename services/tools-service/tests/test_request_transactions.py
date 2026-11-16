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

from .test_calls import MODULE, Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]
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
    ("PUT", "/v1/send-policy", {"text": "Never send a card number."}),
    ("GET", "/v1/send-policy", None),
    ("POST", "/v1/secrets", {"name": "TX_KEY", "value": "tx-value-1"}),
    ("GET", "/v1/secrets", None),
    ("GET", "/v1/secrets?page=1&pageSize=5", None),
    ("POST", "/v1/secrets/TX_KEY/rotate", {"value": "tx-value-2"}),
    ("POST", "/v1/secrets/TX_KEY/rename", {"name": "TX_KEY_2"}),
    ("DELETE", "/v1/secrets/TX_KEY_2", None),
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
        assert r.status_code in (200, 201, 204), (path, r.text)
    assert counts == {f"{m} {p}": 1 for m, p, _ in ROUTES}, counts


async def _counted(
    c: httpx.AsyncClient, method: str, path: str, body: object, headers: dict[str, str], **params: int | str
) -> tuple[httpx.Response, int]:
    """The answer and how many transactions the request held, from its request line."""
    with captured_logging("tools-tx") as stream:
        r = await c.request(method, path, json=body, headers=headers, params=params or None)
    line = next(json.loads(x) for x in stream.getvalue().splitlines() if '"http.request"' in x)
    return r, int(line["db.tx_count"])


async def test_an_operations_mocks_are_changed_and_paged_in_one_transaction(gateway: Gateway) -> None:  # noqa: F811
    base = f"/v1/tool-modules/{MODULE}/operations/{MODULE}_op1/mocks"
    c = gateway.client
    counts: dict[str, int] = {}
    made: list[str] = []
    for i in range(3):
        r, counts[f"add {i}"] = await _counted(c, "POST", base, {"name": f"m{i}"}, {})
        assert r.status_code == 201, r.text
        made.append(r.json()["data"]["id"])
    r, counts["list"] = await _counted(c, "GET", base, None, {}, page=2, pageSize=2)
    assert r.status_code == 200, r.text
    page = r.json()["data"]
    assert ([m["name"] for m in page["data"]], page["operation"]) == (["m2"], gateway.tool("get_account"))
    assert (page["pagination"]["page"], page["pagination"]["total"]) == (2, 3)
    r, counts["change"] = await _counted(c, "PATCH", f"{base}/{made[0]}", {"name": "m0b"}, {})
    assert r.status_code == 200, r.text
    r, counts["delete"] = await _counted(c, "DELETE", f"{base}/{made[1]}", None, {})
    assert r.status_code == 204, r.text
    assert counts == dict.fromkeys(["add 0", "add 1", "add 2", "list", "change", "delete"], 1), counts


async def test_an_mcp_links_routes_each_hold_one_transaction(gateway: Gateway) -> None:  # noqa: F811
    c = gateway.client
    counts: dict[str, int] = {}
    # A picked workflow, which the start checks, not the create: the dev caller's team runs no module's tools.
    made = {"name": "Tx links", "tools": [{"id": "workflow:wf_tx", "label": "Tx flow"}]}
    r, counts["create"] = await _counted(c, "POST", "/v1/mcp-links", made, {})
    assert r.status_code == 201, r.text
    link = f"/v1/mcp-links/{r.json()['data']['id']}"
    for name, method, path, body in (
        ("list", "GET", "/v1/mcp-links", None),
        ("get", "GET", link, None),
        ("pause", "PATCH", link, {"paused": True}),
        ("delete", "DELETE", link, None),
    ):
        r, counts[name] = await _counted(c, method, path, body, {})
        assert r.status_code in (200, 204), (name, r.text)
    assert counts == dict.fromkeys(["create", "list", "get", "pause", "delete"], 1), counts


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
