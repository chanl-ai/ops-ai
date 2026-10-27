"""A connection's credential goes to its own system only (c-330): a module whose address is another host, even one on
the allow-list, gets no credential and nothing is sent; the same module on the connection's address carries it."""

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
    # Made in the module's team: a connection serves its own team's modules only (c-509).
    team = {"X-Team-Id": str(m["team_id"])}
    body = {"name": "Ledger", "authKind": "api_key"}
    made = (await g.client.post("/v1/connections", json=body, headers=team)).json()["data"]
    body = {
        "revision": made["revision"],
        "settings": {"name": "X-Api-Key", "baseUrl": base_url},
        "secretValues": {"key": "k-1"},
    }
    put = await g.client.put(f"/v1/connections/{made['id']}/environments/test", json=body, headers=team)
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


async def test_a_module_on_another_host_gets_no_credential(gateway: Gateway, engine: AsyncEngine) -> None:  # noqa: F811
    g = gateway
    # elsewhere.test stands for any other host the tenant allows; the module calls bank.test.
    await _connect(g, engine, "https://elsewhere.test")
    before = len(g.received)
    refused = await _call(g, "b1")
    assert refused["ok"] is False and refused["output"]["error"]["code"] == "CONNECTION_HOST_MISMATCH", refused
    assert len(g.received) == before, "a request left with another system's credential"


async def test_the_connections_own_host_gets_its_credential(gateway: Gateway, engine: AsyncEngine) -> None:  # noqa: F811
    g = gateway
    await _connect(g, engine, "https://bank.test")
    sent = await _call(g, "b2")
    assert sent["ok"], sent
    assert g.received[-1]["headers"].get("x-api-key") == "k-1"
