"""store/module_list.py: the Tools list names its tenant and the caller's team in the query, so another tenant's or
team's module never appears, in a team scope and in the tenant-wide scope a dev header caller reads in."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_tools.modules.seed import blank
from ops_tools.store.module_list import ModuleList, Window
from ops_tools.store.modules import ModuleStore

NOW = datetime.now(UTC)


async def _module(engine: AsyncEngine, tenant: str, team: str | None, module_id: str) -> None:
    m = blank(
        module_id=module_id,
        tenant_id=tenant,
        team_id=team,
        owner="Operations",
        me="James Richardson",
        at=NOW,
        input={"displayName": module_id, "name": module_id, "type": "http"},
    )
    with isolation.scope(tenant, team):
        await ModuleStore(engine).put(m, expected_revision=None)


@pytest.mark.parametrize("wide", [False, True], ids=["team scope", "tenant-wide request"])
async def test_the_list_shows_only_the_tenant_and_teams_own_and_shared_modules(
    engine: AsyncEngine, tenant: str, wide: bool
) -> None:
    other = f"t_{uuid4().hex[:10]}"
    for t, team, mid in [
        (tenant, "team_a", "mod_own"),
        (tenant, None, "mod_shared"),
        (tenant, "team_b", "mod_other_team"),
        (other, "team_a", "mod_other_tenant"),
    ]:
        await _module(engine, t, team, mid)
    w = Window(now=NOW, expiring=timedelta(days=7), failing_rate=0.02, since="", call_teams=["team_a"], plugins=[])
    listing = ModuleList(engine)
    with isolation.tenant_wide("TESTS", tenant_id=tenant) if wide else isolation.scope(tenant, "team_a"):
        first, second = ListParams(page_size=1), ListParams(page=2, page_size=1)
        page, totals = await listing.page(tenant, "team_a", first, view="all", w=w, seen_by="team_a")
        rest, _ = await listing.page(tenant, "team_a", second, view="all", w=w, seen_by="team_a")
    assert totals["all"] == page["pagination"]["total"] == 2
    assert sorted(str(r["id"]) for r in [*page["data"], *rest["data"]]) == ["mod_own", "mod_shared"]
