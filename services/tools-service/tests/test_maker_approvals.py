"""Writes whose maker asks first (a plugin manifest's or a seed's requires_approval), by failure mode: a new workspace,
whose appChanges says makers' asks are off, still waiting on them; an admin's own answer on a tool being dropped with
them; and a team added later in that workspace not getting the workspace's value. platform-service is a fake here."""

from __future__ import annotations

from typing import Any

import httpx

from ops_tools.modules.policy import WriteApprovals

from .service_clients import fake_service

PLUGIN = {"id": "mod_sf", "template_id": "plugin:salesforce", "operations": [
    {"name": "salesforce_update", "access": "write", "approval_mode": "reviewer"}]}  # fmt: skip
SEEDED = {"id": "mod_bank", "operations": [
    {"name": "hold_account", "access": "write", "approval_mode": "reviewer", "requires_approval": True}]}  # fmt: skip
ADMINS = {"id": "mod_own", "operations": [{"name": "own_write", "access": "write", "approval_mode": "reviewer"}]}


async def waits(levels: tuple[Any, dict[str, Any]], module: dict[str, Any]) -> bool:
    op = module["operations"][0]
    ans = await WriteApprovals(None).answer(
        "t", "team_ops", module, access="write", setting="reviewer", levels=levels, tool=str(op["name"])
    )
    return bool(ans["waits"])


async def test_a_new_workspace_runs_a_write_its_maker_marked_ask_first() -> None:
    off = ({"makersAsk": False}, {})
    assert not await waits(off, PLUGIN)
    assert not await waits(off, SEEDED)
    # A workspace that saved nothing keeps each maker's ask.
    assert await waits(({}, {}), PLUGIN)
    assert await waits(({}, {}), SEEDED)


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
