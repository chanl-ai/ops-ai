"""`GET /v1/tool-catalog`, the read another service rebuilds its catalogue copy from, by failure mode: a page that
repeats or skips a module, a module or grant of another tenant in the answer, a grant missing so the copy shows a
team none of its granted tools, a module the resync reports otherwise than its live event did (so a copy's tools list
depends on which one it heard last), and a token without `tools:view` reading it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation
from ops_tools.modules.seed import catalog_titles, load
from ops_tools.store.modules import ModuleStore, service_outbox

from .conftest import Api, service_headers

PATH = "/v1/tool-catalog"


async def test_the_pages_hold_every_module_and_grant_of_the_tenant_once_and_no_other_tenants(
    api: Api, engine: AsyncEngine, seed: dict[str, Any], catalog_tools: list[dict[str, Any]]
) -> None:
    other = f"t_{uuid4().hex[:10]}"
    with isolation.tenant_wide("TESTS", tenant_id=other):
        await load(ModuleStore(engine), seed, tenant_id=other, now=datetime.now(UTC), catalog=catalog_tools)
    held = await ModuleStore(engine).all_teams(api.tenant)
    items: list[dict[str, Any]] = []
    after: str | None = None
    for _ in range(len(held) + 1):
        params = {"limit": 2, **({"after": after} if after else {})}
        r = await api.client.get(PATH, params=params, headers=service_headers(api.tenant))
        assert r.status_code == 200, r.text
        page = r.json()["data"]
        items += page["items"]
        after = page["nextCursor"]
        if after is None:
            break
    assert after is None, "the last page says so"
    assert {e["tenantId"] for e in items} == {api.tenant}
    modules = [e["payload"]["id"] for e in items if e["name"] == "tool.module.published"]
    assert modules == sorted(m["id"] for m in held), "every module once, in id order"
    grants = {(e["teamId"], e["payload"]["moduleId"]) for e in items if e["name"] == "tool.team_state.changed"}
    want = {
        (a["workflow_team_id"], m["id"])
        for m in held
        for a in m["approvals"]
        if a["status"] == "approved" and a["workflow_team_id"] not in (None, m["team_id"])
    }
    assert want, "the seed grants a module to another team"
    assert grants == want


async def test_the_resync_reports_a_module_as_its_live_event_did(api: Api, engine: AsyncEngine) -> None:
    store = ModuleStore(engine)
    store.titles = catalog_titles(None)
    module = await store.get(api.tenant, "mod_core_banking")
    assert module is not None
    long = "Reads the loan account. " * 30
    ops = [{**o, "description": long} if o["name"] == "get_loan_account" else o for o in module["operations"]]
    await store.put({**module, "version": "9.0.0", "operations": ops}, expected_revision=module["revision"])
    o = service_outbox.c
    q = sa.select(o.payload).where(o.tenant_id == api.tenant, o.name == "tool.module.published").order_by(o.created_at)
    async with engine.connect() as c:
        live = dict((await c.execute(q)).scalars().all()[-1])
    assert live.pop("revision") == module["revision"] + 1
    r = await api.client.get(PATH, params={"limit": 500}, headers=service_headers(api.tenant))
    [resync] = [e["payload"] for e in r.json()["data"]["items"] if e["payload"]["id"] == "mod_core_banking"]
    assert resync == live, "one shape, whichever path the copy heard"
    # A custom app's card is named by its account (Apps.cards), the one GET /v1/apps?ids= answers for.
    assert (live["templateKind"], live["appCardId"], live["truncated"]) == (
        "custom",
        "int_core_banking_team_platform",
        False,
    )
    [loan] = [x for x in live["operations"] if x["name"] == "get_loan_account"]
    assert loan["title"] == "Get loan account"
    assert loan["description"] == long[:499] + "…", "cut to stay under the receiver's payload limit"


async def test_a_token_without_tools_view_is_refused(api: Api) -> None:
    r = await api.client.get(PATH, headers=service_headers(api.tenant, scopes=[]))
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "scope_required"
