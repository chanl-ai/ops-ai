"""Writes whose maker asks first (a plugin manifest's or a seed's requires_approval), by failure mode: a new workspace,
whose appChanges says makers' asks are off, still waiting on them; an admin's own answer on a tool being dropped with
them; a team added later in that workspace not getting the workspace's value; and a team whose workspace stores no
makers' ask read as on or off instead of refused with the fix. platform-service is a fake here."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import dev_service_signer, mint_service_token
from ops_tools.modules.policy import WriteApprovals
from ops_tools.modules.seed import load
from ops_tools.store.modules import Module, ModuleStore

from .conftest import build_app, opa_client
from .service_clients import fake_service

PLUGIN = {"id": "mod_sf", "template_id": "plugin:salesforce", "operations": [
    {"name": "salesforce_update", "access": "write", "approval_mode": "reviewer"}]}  # fmt: skip
SEEDED = {"id": "mod_bank", "operations": [
    {"name": "hold_account", "access": "write", "approval_mode": "reviewer", "requires_approval": True}]}  # fmt: skip
ADMINS = {"id": "mod_own", "operations": [{"name": "own_write", "access": "write", "approval_mode": "reviewer"}]}


async def waits(levels: tuple[Any, dict[str, Any]], module: dict[str, Any]) -> bool:
    op = module["operations"][0]
    ans = await WriteApprovals(None).answer(
        "t", "team_ops", cast(Module, module), access="write", setting="reviewer", levels=levels, tool=str(op["name"])
    )
    return bool(ans["waits"])


async def test_a_new_workspace_runs_a_write_its_maker_marked_ask_first() -> None:
    off: tuple[dict[str, bool], dict[str, Any]] = ({"makersAsk": False}, {})
    assert not await waits(off, PLUGIN)
    assert not await waits(off, SEEDED)
    # Where makers' asks are on, each maker's ask still waits.
    assert await waits(({"makersAsk": True}, {}), PLUGIN)
    assert await waits(({"makersAsk": True}, {}), SEEDED)


async def test_an_answer_someone_set_on_their_own_tool_still_waits() -> None:
    assert await waits(({"makersAsk": False}, {}), ADMINS)


async def test_a_team_added_later_takes_the_workspaces_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path.rsplit("/", 1)[-1]
        value = {"*": {"makersAsk": False}, "team_ops": {"ask": False}} if key == "appChanges" else {}
        return httpx.Response(200, json={"success": True, "data": {"key": key, "value": value}})

    policy = WriteApprovals(fake_service(handler, "platform", ["settings:view"]))
    team, _ = await policy.levels("t", "team_new")
    assert team.get("makersAsk") is False, team
    ops, _ = await policy.levels("t", "team_ops")
    assert ops.get("makersAsk") is False and ops.get("ask") is False, ops


async def test_a_caller_naming_no_team_takes_the_workspaces_waits_and_none_of_its_loosening() -> None:
    def rules(star: dict[str, Any] | None) -> WriteApprovals:
        def handler(request: httpx.Request) -> httpx.Response:
            key = request.url.path.rsplit("/", 1)[-1]
            value = ({"*": star} if star is not None else {}) if key == "appChanges" else {}
            return httpx.Response(200, json={"success": True, "data": {"key": key, "value": value}})

        return WriteApprovals(fake_service(handler, "platform", ["settings:view"]))

    cases: dict[str, dict[str, Any] | None] = {
        "workspace keeps makers' asks": {"makersAsk": True},
        "workspace asks a reviewer": {"ask": True, "answer": "reviewer", "makersAsk": True},
        "workspace turned makers' asks off": {"makersAsk": False, "testRunsAsk": False},
    }
    seen = {name: (await rules(star).levels("t", None))[0] for name, star in cases.items()}
    assert seen == {
        "workspace keeps makers' asks": {"makersAsk": True},
        "workspace asks a reviewer": {"ask": True, "answer": "reviewer", "makersAsk": True},
        "workspace turned makers' asks off": {},
    }


async def test_a_team_whose_workspace_stores_no_makers_ask_is_refused_with_the_fix(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path.rsplit("/", 1)[-1]
        value = {"*": {"ask": False}, "team_ops": {"ask": False}} if key == "appChanges" else {}
        return httpx.Response(200, json={"success": True, "data": {"key": key, "value": value}})

    policy = WriteApprovals(fake_service(handler, "platform", ["settings:view"]))
    # A caller naming no team keeps every maker's ask, so it needs no value.
    assert (await policy.levels("t", None))[0] == {"ask": False}
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    token = mint_service_token(
        dev_service_signer(), service="agents", audience="tools", tenant_id=tenant, scopes=["tools:view"],
        team_id="team_ops",
    )  # fmt: skip
    async with opa_client() as opa:
        app = build_app(engine, seed, tenant, opa=opa, write_approvals=policy)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as client,
        ):
            body = {
                "tool": "open_case",
                "input": {"subject": "Card stopped"},
                "key": "unset-1",
                "runContext": {"act": "test"},
            }
            r = await client.post("/v1/calls", json=body, headers={"Authorization": f"Bearer {token}"})
    assert (r.status_code, r.json()["error"]["code"]) == (503, "approval_rules_unavailable"), r.text
    assert "Settings, Approvals" in r.json()["error"]["details"]["reasons"][0], r.text
