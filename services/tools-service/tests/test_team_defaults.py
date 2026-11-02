"""Every team's built-in apps come from provisioning (c-616 PV1), by failure mode: a team starts with no built-in
tools; a team reads another team's copy; a second run writes again; a newer declaration skips a team's untouched copy
or overwrites one a person changed; and the team's own module holding a tool is joined by a second copy of it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store.team_scope import acting_as
from ops_tools.defaults import DEFAULTS_VERSION, catch_up, ensure_defaults
from ops_tools.modules.seed import BUILT_IN, blank, built_in_module, platform_module
from ops_tools.registry import ToolRegistry
from ops_tools.store.modules import ModuleStore
from ops_tools.store.team_defaults import TeamDefaults

OPS, RETAIL = "team_ops", "team_retail"
NOW = datetime(2026, 11, 1, tzinfo=UTC)


async def test_a_teams_first_lookup_finds_its_own_built_in_tools(
    local_catalog: Any, store: ModuleStore, tenant: str
) -> None:
    registry = ToolRegistry(local_catalog, store)
    for tool, app in (("search_knowledge", "knowledge"), ("read_file", "files"), ("send_reply", "mailboxes")):
        found = await registry.resolve(tool, tenant_id=tenant, team_id=OPS)
        assert found is not None and found.module is not None, tool
        assert (found.module["team_id"], found.module["template_id"]) == (OPS, f"builtin:{app}"), found.module


async def test_each_team_has_its_own_copy(store: ModuleStore, engine: AsyncEngine, tenant: str) -> None:
    defaults = TeamDefaults(engine)
    for team in (OPS, RETAIL):
        assert await ensure_defaults(store, defaults, tenant_id=tenant, team_id=team, at=NOW)
    ops = await store.get(tenant, f"mod_builtin_files_{OPS}")
    retail = await store.get(tenant, f"mod_builtin_files_{RETAIL}")
    assert ops is not None and retail is not None and (ops["team_id"], retail["team_id"]) == (OPS, RETAIL)


async def test_a_current_team_is_not_written_again(store: ModuleStore, engine: AsyncEngine, tenant: str) -> None:
    defaults = TeamDefaults(engine)
    assert await ensure_defaults(store, defaults, tenant_id=tenant, team_id=OPS, at=NOW)
    assert not await ensure_defaults(store, defaults, tenant_id=tenant, team_id=OPS, at=NOW)
    assert await defaults.version(tenant, OPS) == DEFAULTS_VERSION


async def test_a_newer_version_replaces_an_untouched_copy_and_spares_a_changed_one(
    store: ModuleStore, engine: AsyncEngine, tenant: str
) -> None:
    defaults = TeamDefaults(engine)
    await ensure_defaults(store, defaults, tenant_id=tenant, team_id=OPS, at=NOW)
    files = await store.get(tenant, f"mod_builtin_files_{OPS}")
    assert files is not None
    await store.put({**files, "description": "Changed by a person"}, expected_revision=files["revision"])
    mail = await store.get(tenant, f"mod_builtin_mailboxes_{OPS}")
    assert mail is not None
    await store.put({**mail, "operations": mail["operations"][:1]}, expected_revision=0, seeded=True)
    assert await ensure_defaults(store, defaults, tenant_id=tenant, team_id=OPS, at=NOW, version=DEFAULTS_VERSION + 1)
    assert (await store.get(tenant, f"mod_builtin_files_{OPS}") or {})["description"] == "Changed by a person"
    after = await store.get(tenant, f"mod_builtin_mailboxes_{OPS}")
    assert [o["name"] for o in (after or {})["operations"]] == list(BUILT_IN[1]["operations"])


async def test_a_tool_the_team_holds_in_its_own_module_is_not_copied(
    store: ModuleStore, engine: AsyncEngine, tenant: str
) -> None:
    own = built_in_module(BUILT_IN[2], ["read_file"], tenant_id=tenant, team_id=OPS, at=NOW)
    mine = blank(
        module_id="mod_team_files", tenant_id=tenant, team_id=OPS, owner="Operations", me="t", at=NOW,
        input={"displayName": "Our files", "name": "our-files", "type": "code"},
    )  # fmt: skip
    await store.put(
        {**mine, "status": "published", "operations": [{**own["operations"][0], "id": "mod_team_files_op1"}]},
        expected_revision=None,
    )
    await ensure_defaults(store, TeamDefaults(engine), tenant_id=tenant, team_id=OPS, at=NOW)
    assert await store.get(tenant, f"mod_builtin_files_{OPS}") is None


async def test_start_brings_every_team_behind_up_to_date(store: ModuleStore, engine: AsyncEngine, tenant: str) -> None:
    defaults = TeamDefaults(engine)
    await defaults.record(tenant, RETAIL, 0, NOW)
    assert (tenant, RETAIL) in await catch_up(store, defaults)
    assert await store.get(tenant, f"mod_builtin_knowledge_{RETAIL}") is not None


async def test_a_teams_tools_are_listed_once_beside_an_older_workspace_copy(
    local_catalog: Any, store: ModuleStore, tenant: str
) -> None:
    # An install from before provisioning holds the workspace-level Platform tools module with the built-in reads.
    await store.insert_if_missing(platform_module(["read_file", "open_case"], tenant_id=tenant, at=NOW))
    registry = ToolRegistry(local_catalog, store)
    with acting_as(OPS):
        names = [t["name"] for t in await registry.grantable(tenant, lambda _: True)]
    assert names.count("read_file") == 1 and "open_case" in names, names
