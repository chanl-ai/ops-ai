"""The platform's own workflow tools (send_reply, open_case) resolve in every install, by failure mode: only the dev
seed's modules held them, so a production install, which skips the seed, refused a workflow's reply with "tool
send_reply is not registered with the gateway" (staging, wfrun_d150e5be12e3); a second first call writes the module
twice; an install's own edit of the module is overwritten. Runs on a fresh tenant with no seed."""

from __future__ import annotations

import asyncio
from typing import Any

from ops_tools.registry import ToolRegistry
from ops_tools.store.modules import ModuleStore

# The module the platform tools live in, in every install (and the id the staging script wrote).
PLATFORM_MODULE = "mod_platform_tools"


async def test_a_fresh_install_resolves_the_platform_tools(local_catalog: Any, store: ModuleStore, tenant: str) -> None:
    registry = ToolRegistry(local_catalog, store)
    reply = await registry.resolve("send_reply", tenant_id=tenant)
    assert reply is not None and reply.module is not None and reply.operation is not None, reply
    assert (reply.module["id"], reply.executor, reply.access) == (PLATFORM_MODULE, "local", "write")
    assert reply.operation["requires_approval"] is True
    case = await registry.resolve("open_case", tenant_id=tenant)
    assert case is not None and case.module is not None and case.module["id"] == PLATFORM_MODULE, case
    # A builder can grant open_case to an agent before any workflow has called it.
    assert "open_case" in {t["name"] for t in await registry.grantable(tenant)}


async def test_first_calls_at_once_write_one_module(local_catalog: Any, store: ModuleStore, tenant: str) -> None:
    calls = [ToolRegistry(local_catalog, store).resolve("send_reply", tenant_id=tenant) for _ in range(4)]
    assert all(r is not None for r in await asyncio.gather(*calls))
    assert [m["id"] for m in await store.all(tenant) if m["id"] == PLATFORM_MODULE] == [PLATFORM_MODULE]


async def test_an_edited_platform_module_is_kept(local_catalog: Any, store: ModuleStore, tenant: str) -> None:
    await ToolRegistry(local_catalog, store).resolve("send_reply", tenant_id=tenant)
    stored = await store.get(tenant, PLATFORM_MODULE)
    assert stored is not None
    await store.put({**stored, "description": "Ours"}, expected_revision=stored["revision"])
    await ToolRegistry(local_catalog, store).resolve("open_case", tenant_id=tenant)
    kept = await store.get(tenant, PLATFORM_MODULE)
    assert kept is not None and kept["description"] == "Ours", kept


class _Teams:
    """platform-service's workspace teams as the registry reads them (modules.policy.WorkspaceTeams)."""

    def __init__(self, team: str | None) -> None:
        self.team, self.reads = team, 0

    async def security_team(self, tenant_id: str) -> str | None:
        del tenant_id  # one workspace per test
        self.reads += 1
        return self.team


async def test_a_workspace_with_its_own_security_team_owns_its_platform_tools(
    local_catalog: Any, store: ModuleStore, tenant: str
) -> None:
    """Tick 36: the module took the install's security team, so a workspace that names its own sent send_reply's
    approvals to a team that may not be its own."""
    registry = ToolRegistry(local_catalog, store, workspace_teams=_Teams("team_infosec"))
    reply = await registry.resolve("send_reply", tenant_id=tenant)
    assert reply is not None and reply.module is not None and reply.module["team_id"] == "team_infosec", reply


async def test_an_unreadable_security_team_writes_no_module_until_it_can_be_read(
    local_catalog: Any, store: ModuleStore, tenant: str
) -> None:
    """Platform-service down: writing the install's team then would keep the wrong owner after it recovers."""
    down = _Teams(None)
    registry = ToolRegistry(local_catalog, store, workspace_teams=down)
    assert await registry.resolve("send_reply", tenant_id=tenant) is None
    assert await store.get(tenant, PLATFORM_MODULE) is None
    down.team = "team_infosec"
    reply = await registry.resolve("send_reply", tenant_id=tenant)
    assert reply is not None and reply.module is not None and reply.module["team_id"] == "team_infosec", reply
