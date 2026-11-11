"""Each app's "Ask before changes" switch as the grantable operations carry it to agents-service, by failure mode:

- a write of an app nobody switched off is handed to agents as one that runs without asking;
- a read is marked as asking, so chat would stop on every lookup;
- an app a team admin switched off (appsChangeWithoutAsking) still asks, or one switched off asks no more for every app;
- a switch that cannot be read lets writes run without asking, where a failed read must keep asking.

Whether the person in chat is then asked is agents-service's (test_ask_first_chat there); the gateway's own approvals
(test_approvals_off_by_default) are unchanged by the switch.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.modules.policy import WriteApprovals
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, opa_client, service_headers


class Quiet(WriteApprovals):
    """The apps the team switched "Ask before changes" off for, as the live read answers it (None: unreadable)."""

    def __init__(self, quiet: Callable[[list[dict[str, Any]]], list[str] | None]) -> None:
        super().__init__(cast(Any, None))
        self.pick = quiet
        self.modules: list[dict[str, Any]] = []

    async def all_writes(self, tenant_id: str, team_id: str | None) -> bool:
        return False

    async def apps(self, tenant_id: str, team_id: str | None) -> list[str] | None:
        return []

    async def change_without_asking(self, tenant_id: str, team_id: str | None) -> list[str] | None:
        return self.pick(self.modules)


Rows = Callable[[Quiet], Any]


@pytest.fixture
def grantable(engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]) -> Rows:
    async def rows(approvals: Quiet) -> dict[str, dict[str, Any]]:
        await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
        approvals.modules = await ModuleStore(engine).all_teams(tenant)
        async with opa_client() as opa:
            app = build_app(engine, seed, tenant, opa=opa, write_approvals=approvals)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c,
            ):
                r = await c.get("/v1/grantable-operations", headers=service_headers(tenant))
                assert r.status_code == 200, r.text
                return {str(o["name"]): o for o in r.json()["data"]}

    return rows


def _module_of(modules: list[dict[str, Any]], tool: str) -> str:
    return next(f"module:{m['id']}" for m in modules if any(o["name"] == tool for o in m["operations"]))


async def test_every_write_asks_first_and_no_read_does(grantable: Rows) -> None:
    rows = await grantable(Quiet(lambda _: []))
    writes = [o for o in rows.values() if o["access"] != "read"]
    assert writes and all(o["asksFirst"] is True for o in writes), writes
    assert all(o["asksFirst"] is False for o in rows.values() if o["access"] == "read"), rows


async def test_an_app_switched_off_runs_its_writes_without_asking_and_others_still_ask(grantable: Rows) -> None:
    rows = await grantable(Quiet(lambda mods: [_module_of(mods, "open_case")]))
    assert rows["open_case"]["asksFirst"] is False, rows["open_case"]
    others = [o for o in rows.values() if o["access"] != "read" and o.get("moduleId") != rows["open_case"]["moduleId"]]
    assert others and all(o["asksFirst"] is True for o in others), others


async def test_a_switch_that_cannot_be_read_keeps_every_write_asking(grantable: Rows) -> None:
    rows = await grantable(Quiet(lambda _: None))
    assert rows["open_case"]["asksFirst"] is True, rows["open_case"]
