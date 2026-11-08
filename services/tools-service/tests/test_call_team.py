"""Each call is logged with the team it was made in, by failure mode, through the real call route with a service
token naming the run's team:

- a call on a module no team owns (the platform tools) is logged with no team, or with the module's (empty) team, so
  it shows in every team's Usage instead of only the calling team's;
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import dev_service_signer, mint_service_token
from ops_tools.modules.seed import load
from ops_tools.store.calls import gateway_calls
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, opa_client

LENDING = "team_lending"
CARDS = "team_cards"


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


async def _call(gw: httpx.AsyncClient, tenant: str, team: str, tool: str, key: str) -> str:
    body = {"tool": tool, "input": {}, "key": f"{key}-{team}", "runContext": {"act": "test"}}
    r = await gw.post("/v1/calls", json=body, headers=run_of(tenant, team))
    data = r.json()
    call_id = data.get("callId") or data.get("error", {}).get("details", {}).get("callId")
    assert call_id, r.text
    return str(call_id)


async def _team_of(engine: AsyncEngine, tenant: str, call_id: str) -> str | None:
    q = sa.select(gateway_calls.c.team_id).where(gateway_calls.c.tenant_id == tenant, gateway_calls.c.id == call_id)
    async with engine.connect() as c:
        return (await c.execute(q)).scalar_one()


async def test_a_call_on_a_shared_module_is_logged_with_the_calling_team(
    gw: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    call_id = await _call(gw, tenant, LENDING, "open_case", "shared")
    assert await _team_of(engine, tenant, call_id) == LENDING


def reader_of(team: str) -> dict[str, str]:
    """The call log is read under activity.view, which a service's token does not carry; the dev person in the team
    reads it here, as the console does."""
    return {"X-Team-Id": team}


async def _listed(gw: httpx.AsyncClient, tenant: str, team: str) -> dict[str, dict[str, Any]]:
    r = await gw.get("/v1/executions", params={"pageSize": 100}, headers=reader_of(team))
    assert r.status_code == 200, r.text
    return {row["id"]: row for row in r.json()["data"]["data"]}


async def test_usage_never_shows_another_teams_call_on_a_shared_module(gw: httpx.AsyncClient, tenant: str) -> None:
    call_id = await _call(gw, tenant, LENDING, "open_case", "usage")
    assert call_id in await _listed(gw, tenant, LENDING), "the calling team sees its own call"
    assert call_id not in await _listed(gw, tenant, CARDS), "another team sees nothing of it"
    r = await gw.get(f"/v1/executions/{call_id}", headers=reader_of(CARDS))
    assert r.status_code == 404, r.text


async def test_usage_says_whom_a_call_ran_as(gw: httpx.AsyncClient, tenant: str) -> None:
    call_id = await _call(gw, tenant, LENDING, "open_case", "as")
    assert (await _listed(gw, tenant, LENDING))[call_id]["runAs"] == {"kind": "team"}
