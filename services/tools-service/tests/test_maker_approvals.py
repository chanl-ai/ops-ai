"""Writes whose maker asks first (a plugin manifest's or a seed's requires_approval), by failure mode: a new workspace,
whose appChanges says makers' asks are off, still waiting on them; an admin's own answer on a tool being dropped with
them; a team added later in that workspace not getting the workspace's value; and a workspace that stores no makers' ask
read as on or off. platform-service is a fake here."""

from __future__ import annotations

from typing import Any, cast

import httpx

from ops_tools.modules.policy import WriteApprovals
from ops_tools.store.modules import Module

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


async def test_a_workspace_that_stores_no_makers_ask_has_its_rules_unread() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path.rsplit("/", 1)[-1]
        value = {"*": {"ask": False}, "team_ops": {"ask": False}} if key == "appChanges" else {}
        return httpx.Response(200, json={"success": True, "data": {"key": key, "value": value}})

    policy = WriteApprovals(fake_service(handler, "platform", ["settings:view"]))
    # Unread, for a team and for a caller naming none: the gateway refuses the write (approval_rules_unavailable).
    assert [(await policy.levels("t", team))[0] for team in ("team_ops", None)] == [None, None]
