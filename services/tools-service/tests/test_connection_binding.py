"""A connection's credential goes to its own system only, and a custom app's base address is its connection's: a
connection on a host the module was never reviewed for sends nothing, and the module calls the connection's
own address with its credential."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.modules import ModuleStore

from .conftest import service_headers
from .test_calls import MODULE, Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]


async def _connect(g: Gateway, engine: AsyncEngine, base_url: str) -> str:
    store = ModuleStore(engine)
    m = await store.get(g.tenant, MODULE)
    assert m is not None
    # Made in the module's team: a connection serves its own team's modules only.
    team = {"X-Team-Id": str(m["team_id"])}
    body = {"name": "Ledger", "authKind": "api_key"}
    made = (await g.client.post("/v1/apps", json=body, headers=team)).json()["data"]
    body = {
        "revision": made["revision"],
        "settings": {"name": "X-Api-Key", "baseUrl": base_url},
        "secretValues": {"key": "k-1"},
    }
    put = await g.client.patch(f"/v1/apps/{made['id']}/accounts/{made['id']}", json=body, headers=team)
    assert put.status_code == 200, put.text
    await store.put({**m, "connection_id": made["id"]}, expected_revision=m["revision"])
    return str(made["id"])


async def _call(g: Gateway, step: str) -> dict[str, Any]:
    body = {
        "tool": g.tool("get_account"),
        "input": {"accountId": "CHQ-2219"},
        "key": step,
        "runContext": {"thread": g.thread, "step": step, "act": "agent:dispute_triage", "environment": "test"},
    }
    res = await g.client.post("/v1/calls", json=body, headers=service_headers(g.tenant))
    assert res.status_code == 200, res.text
    return res.json()["data"]


async def test_a_connection_moved_to_another_host_sends_nothing(gateway: Gateway, engine: AsyncEngine) -> None:  # noqa: F811
    g = gateway
    # elsewhere.test stands for any host the module's reviewed egress hosts do not name (they name bank.test).
    await _connect(g, engine, "https://elsewhere.test")
    before = len(g.received)
    refused = await _call(g, "b1")
    assert refused["ok"] is False and refused["output"]["error"]["code"] == "EGRESS_DENIED", refused
    assert len(g.received) == before, "a request left for a host the module was not reviewed for"


async def test_the_connections_own_address_gets_its_credential(gateway: Gateway, engine: AsyncEngine) -> None:  # noqa: F811
    g = gateway
    await _connect(g, engine, "https://bank.test/v1")
    sent = await _call(g, "b2")
    assert sent["ok"], sent
    assert g.received[-1]["headers"].get("x-api-key") == "k-1"
