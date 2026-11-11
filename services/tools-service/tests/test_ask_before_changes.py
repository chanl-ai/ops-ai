"""Each app's "Ask before changes" switch as the grantable operations carry it to agents-service, by failure mode:

- a write that declares approval is handed to agents as one that waits (requiresApproval);
- a read never waits;
- an app a team admin set to don't ask (appChangesByApp) does not hold a write with no setting of its own, and a tool
  that declares approval still waits: the tool's answer is more specific than its app's;
- a team policy that cannot be read keeps writes waiting.

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
    """The levels the team set, as the live read answers them: the apps `pick` names (by module id) answer "don't ask";
    `pick` returning None is a team policy that could not be read."""

    def __init__(self, quiet: Callable[[list[dict[str, Any]]], list[str] | None]) -> None:
        super().__init__(cast(Any, None))
        self.pick = quiet
        self.modules: list[dict[str, Any]] = []

    async def levels(self, tenant_id: str, team_id: str | None) -> tuple[Any, dict[str, Any]]:
        named = self.pick(self.modules)
        if named is None:
            return None, {}
        return {"ask": True, "answer": "reviewer", "reviewerRole": None}, {i: {"answer": "none"} for i in named}


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


async def test_a_write_that_declares_approval_waits_and_no_read_does(grantable: Rows) -> None:
    rows = await grantable(Quiet(lambda _: []))
    assert rows["update_address"]["requiresApproval"] is True and rows["place_wire_hold"]["requiresApproval"] is True
    assert all(o["requiresApproval"] is False for o in rows.values() if o["access"] == "read"), rows


async def test_a_tool_that_declares_approval_still_waits_where_its_app_is_set_to_dont_ask(grantable: Rows) -> None:
    rows = await grantable(Quiet(lambda mods: [_module_of(mods, "update_address")]))
    assert rows["update_address"]["requiresApproval"] is True, rows["update_address"]
    assert rows["update_address"]["source"] == "tool", rows["update_address"]


async def test_a_switch_that_cannot_be_read_keeps_the_write_waiting(grantable: Rows) -> None:
    rows = await grantable(Quiet(lambda _: None))
    assert rows["update_address"]["requiresApproval"] is True, rows["update_address"]
