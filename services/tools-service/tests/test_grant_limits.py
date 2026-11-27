"""What a cross-team grant and a caller with no team reach at the gateway, by failure mode, through the real call and
grant-list routes with service tokens, on two tenants seeded alike:

- a grant past its end date still lists and calls the module's operations;
- a grant naming some of a module's operations opens every one of them;
- a write by a caller that names no team skips the workspace's approval level (`*` of appChanges) and runs.

Every refusal still writes its call-log row.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import dev_service_signer, mint_service_token
from ops_tools.modules.policy import WriteApprovals
from ops_tools.modules.seed import load
from ops_tools.store.calls import gateway_calls
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, fake_service, opa_client

CARDS = "team_cards"
# Platform-owned; team_cards' workflow is granted get_customer_profile and update_address, and not get_loan_account.
BANK = "mod_core_banking"
INPUT = {"get_customer_profile": {"customerId": "CUS-1001"}, "get_loan_account": {"loanAccountId": "LN-1"}}
CASE = {"subject": "Card stopped working abroad"}


def run_of(tenant: str, team: str | None) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="agents", audience="tools", tenant_id=tenant, scopes=["tools:view"], team_id=team
    )
    return {"Authorization": f"Bearer {token}"}


def workspace_asks_a_reviewer() -> WriteApprovals:
    """platform-service's answer for a workspace whose own value (`*`) asks a reviewer and whose teams saved none."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path.rsplit("/", 1)[-1]
        value = {"*": {"ask": True, "answer": "reviewer", "makersAsk": True}} if key == "appChanges" else {}
        return httpx.Response(200, json={"success": True, "data": {"key": key, "value": value}})

    return WriteApprovals(fake_service(handler, "platform", ["settings:view"]))


@pytest.fixture
async def gw(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    now = datetime.now(UTC)
    for t in (tenant, f"{tenant}b"):
        await load(ModuleStore(engine), seed, tenant_id=t, now=now, catalog=catalog_tools)
    async with opa_client() as opa:
        app = build_app(engine, seed, tenant, opa=opa, write_approvals=workspace_asks_a_reviewer())
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c,
        ):
            yield c


async def _end_grant(engine: AsyncEngine, tenant: str, module_id: str, team: str) -> None:
    store = ModuleStore(engine)
    m = await store.get(tenant, module_id)
    assert m is not None
    for a in m["approvals"]:
        if a["workflow_team_id"] == team and a["status"] == "approved":
            a["expires_at"] = datetime.now(UTC) - timedelta(days=1)
    await store.put(m, expected_revision=m["revision"])


async def _call(gw: httpx.AsyncClient, tenant: str, team: str | None, tool: str, key: str) -> tuple[int, str | None]:
    body = {"tool": tool, "input": INPUT.get(tool, CASE), "key": f"{key}-{tenant}", "runContext": {"act": "test"}}
    r = await gw.post("/v1/calls", json=body, headers=run_of(tenant, team))
    error: dict[str, Any] = r.json().get("error") or {}
    return r.status_code, error.get("code")


async def _listed(gw: httpx.AsyncClient, tenant: str, team: str) -> set[str]:
    r = await gw.get("/v1/grantable-operations", headers=run_of(tenant, team))
    assert r.status_code == 200, r.text
    return {str(o["name"]) for o in r.json()["data"] if (o.get("moduleId") or o.get("module_id")) == BANK}


async def _modules(gw: httpx.AsyncClient, team: str) -> list[str]:
    """The module list as the dev person in `team` reads it, as the console does."""
    r = await gw.get("/v1/tool-modules", params={"ids": BANK}, headers={"X-Team-Id": team})
    assert r.status_code == 200, r.text
    return [str(m["id"]) for m in r.json()["data"]["data"]]


async def _refusals(engine: AsyncEngine, tenant: str, tool: str) -> list[str]:
    q = sa.select(gateway_calls.c.outcome).where(gateway_calls.c.tenant_id == tenant, gateway_calls.c.tool == tool)
    async with engine.connect() as c:
        return [str(o) for o in (await c.execute(q)).scalars()]


async def test_a_grant_reaches_only_its_operations_and_nothing_once_it_ended(
    gw: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    other = f"{tenant}b"
    await _end_grant(engine, tenant, BANK, CARDS)
    seen = {
        "listed, grant ended": await _listed(gw, tenant, CARDS),
        "listed, other tenant's grant": await _listed(gw, other, CARDS),
        "call, grant ended": await _call(gw, tenant, CARDS, "get_customer_profile", "ended"),
        "call, not granted": await _call(gw, other, CARDS, "get_loan_account", "ungranted"),
        "call, other tenant's grant": await _call(gw, other, CARDS, "get_customer_profile", "live"),
        "module list, grant ended": await _modules(gw, CARDS),
    }
    assert seen == {
        "listed, grant ended": set(),
        "listed, other tenant's grant": {"get_customer_profile", "update_address"},
        # An ended grant no longer resolves the name for the team, so the tool is unknown to it.
        "call, grant ended": (403, "gateway_refused"),
        "call, not granted": (403, "team_forbidden"),
        # Past the team check: the read runs on the fake bank's test account.
        "call, other tenant's grant": (200, None),
        "module list, grant ended": [],
    }
    assert await _refusals(engine, tenant, "get_customer_profile") == ["refused"]
    assert await _refusals(engine, other, "get_loan_account") == ["refused"]


async def test_a_write_by_a_caller_naming_no_team_waits_as_the_workspace_asks(
    gw: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    # open_case is workspace-level and has no setting of its own, so only the team level decides whether it waits.
    held = {team: await _call(gw, tenant, team, "open_case", f"ws-{team}") for team in ("team_lending", None)}
    assert held == {"team_lending": (403, "gateway_refused"), None: (403, "gateway_refused")}, held
    assert await _refusals(engine, tenant, "open_case") == ["refused", "refused"]
