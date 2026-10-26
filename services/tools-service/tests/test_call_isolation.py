"""A run reaches another team's tool module only through an approved grant (c-433), by failure mode, through the real
call and grant-list routes with a service token naming the run's team:

- a call to another team's module with no grant runs;
- a call to a module approved for one of the team's workflows is refused (the grant also covers the team's agents);
- the grant list offers another team's ungranted operations to the team's agents;
- the platform tools, a module no team owns, are refused to a team.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import dev_service_signer, mint_service_token
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, grant, opa_client

LENDING = "team_lending"


def run_of(tenant: str, team: str) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="agents", audience="tools", tenant_id=tenant, scopes=["tools:view"], team_id=team
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def gw(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    async with opa_client() as opa:
        app = build_app(engine, seed, tenant, opa=opa)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c,
        ):
            yield c


async def _read_op(engine: AsyncEngine, tenant: str, module_id: str) -> str:
    m = await ModuleStore(engine).get_any(tenant, module_id)
    assert m is not None
    return next(o["name"] for o in m["operations"] if o.get("access") == "read" and o.get("enabled", True))


async def _call(gw: httpx.AsyncClient, tenant: str, team: str, tool: str) -> httpx.Response:
    body = {"tool": tool, "input": {}, "key": f"k-{team}-{tool}", "runContext": {"act": "test"}}
    return await gw.post("/v1/calls", json=body, headers=run_of(tenant, team))


async def test_a_call_to_another_teams_module_is_refused(
    gw: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    tool = await _read_op(engine, tenant, "mod_payments_hub")
    r = await _call(gw, tenant, LENDING, tool)
    # The name is unique per team (c-509): another team's operation is not found, and the refusal names no owner.
    assert r.status_code == 403 and r.json()["error"]["code"] == "gateway_refused", r.text
    assert "not registered" in r.json()["error"]["message"]


async def test_a_grant_to_the_teams_workflow_lets_its_runs_call(
    gw: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    store = ModuleStore(engine)
    m = await store.get_any(tenant, "mod_core_banking")
    assert m is not None
    ours = next(a for a in m["approvals"] if a.get("workflow_team_id") == LENDING)
    await grant(engine, tenant, "mod_core_banking", ours["id"])
    tool = await _read_op(engine, tenant, "mod_core_banking")
    r = await _call(gw, tenant, LENDING, tool)
    assert not (r.status_code == 403 and r.json()["error"]["code"] == "team_forbidden"), r.text


async def test_the_grant_list_leaves_out_another_teams_ungranted_operations(
    gw: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    payments = await _read_op(engine, tenant, "mod_payments_hub")
    everyone = {
        o["name"] for o in (await gw.get("/v1/grantable-operations", headers=run_of(tenant, ""))).json()["data"]
    }
    assert payments in everyone, "a token naming no team acts for the tenant"
    r = await gw.get("/v1/grantable-operations", headers=run_of(tenant, LENDING))
    assert r.status_code == 200, r.text
    assert payments not in {o["name"] for o in r.json()["data"]}


async def test_the_platform_tools_are_called_by_any_team(gw: httpx.AsyncClient, tenant: str) -> None:
    r = await gw.get("/v1/grantable-operations", headers=run_of(tenant, "team_d90630bcb0e7"))
    assert r.status_code == 200, r.text
    assert "open_case" in {o["name"] for o in r.json()["data"]}, "a team the seed does not hold reaches open_case"
