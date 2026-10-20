"""The open_case tool (c-219), by failure mode: a case opened in a team the call does not act in; a retried call
opening a second case; a call with no team opening one anyway; the tool missing from a tenant's registry."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore
from ops_tools.tools import LocalToolRunner, ToolCaller

from .conftest import Catalog, MemorySender
from .service_clients import claims, fake_service

CALLER = ToolCaller(tenant_id="t_a", team_id="team_ops", sub="agent:ag_dispute", kind="service")


class Agents:
    def __init__(self) -> None:
        self.sent: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.sent.append((claims(request), json.loads(request.content)))
        return httpx.Response(201, json={"success": True, "data": {"id": "case_1", "status": "open"}})


def runner(agents: Agents, catalog: Catalog) -> LocalToolRunner:
    cases = fake_service(agents, "agents", ["cases:view", "cases:create"])
    return LocalToolRunner(catalog, MemorySender(), cases=cases)


async def test_a_case_opens_in_the_callers_team_keyed_by_the_call(local_catalog: Catalog) -> None:
    agents = Agents()
    args = {"subject": "Card dispute", "customerId": "C-1001"}
    out = await runner(agents, local_catalog).run("open_case", args, key="gth_1:s3", caller=CALLER)
    assert (out.ok, out.output) == (True, {"caseId": "case_1", "status": "open"})
    [(token, body)] = agents.sent
    assert (token["tenant_id"], token["team_id"], token["scopes"]) == (
        "t_a",
        "team_ops",
        ["cases:view", "cases:create"],
    )
    assert body["producerKey"] == "tool:gth_1:s3" and body["priority"] == "normal"


async def test_a_call_that_acts_in_no_team_opens_nothing(local_catalog: Catalog) -> None:
    agents = Agents()
    caller = ToolCaller(tenant_id="t_a", team_id=None, sub="agent:ag_dispute", kind="service")
    out = await runner(agents, local_catalog).run("open_case", {"subject": "x"}, key="k", caller=caller)
    assert out.ok is False and agents.sent == []


async def test_every_tenant_registry_holds_open_case_as_a_tool_needing_no_approval(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    ops = [o for m in await ModuleStore(engine).all(tenant) for o in m["operations"] if o["name"] == "open_case"]
    assert [(o["access"], o["executor"], o["requires_approval"]) for o in ops] == [("write", "local", False)]
