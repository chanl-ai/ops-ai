"""`GET /v1/tool-catalog`, the read another service rebuilds its catalogue copy from, by failure mode: a page that
repeats or skips a module, a module or grant of another tenant in the answer, a grant missing so the copy shows a
team none of its granted tools, and a token without `tools:view` reading it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

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


async def test_a_token_without_tools_view_is_refused(api: Api) -> None:
    r = await api.client.get(PATH, headers=service_headers(api.tenant, scopes=[]))
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "scope_required"
