"""The workspace's memory retention (c-206), by failure mode: an expired memory survives, a kept one is deleted, the
deletion is not audited, or a policy that cannot be read deletes anything."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from ops_agents.api.memory_retention import PlatformRetention, expire_memories
from ops_agents.api.runs import graph_store
from ops_agents.store.memories import agent_memories
from ops_agents.store.tenancy import tenant_scope, tenant_tx
from ops_identity import ServiceClient, dev_service_signer
from tests.api.test_action_roles import VIEWER
from tests.api.test_memory import MINE, chat, mine
from tests.api.test_team_default_agent import Stack, say, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import TENANT

NOW = datetime(2026, 10, 18, tzinfo=UTC)


class Days:
    def __init__(self, days: float | None) -> None:
        self.value = days

    async def days(self) -> float | None:
        return self.value


async def aged(rt: object, key: str, days: int) -> None:
    at = (NOW - timedelta(days=days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    with tenant_scope(TENANT):
        async with tenant_tx(graph_store(rt).engine) as c:  # pyright: ignore[reportArgumentType]
            await c.execute(agent_memories.update().where(agent_memories.c.key == key).values(created_at=at))


async def test_memories_past_the_policy_are_deleted_and_audited_and_the_rest_kept(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await say(c, await chat(c, VIEWER), "My timezone is Eastern.", VIEWER)
    await say(c, await chat(c, VIEWER), "My preferred account is CHQ-2219.", VIEWER)
    await aged(rt, "timezone", 40)
    await aged(rt, "preferred account", 10)
    assert await expire_memories(rt, Days(None), NOW) == 0, "no policy keeps everything"
    assert len(await mine(c, VIEWER)) == 2
    assert await expire_memories(rt, Days(30), NOW) == 1
    assert [m["key"] for m in await mine(c, VIEWER)] == ["preferred account"]
    audit = (await c.get(f"{MINE}/export", headers=VIEWER)).json()["data"]["audit"]
    assert [(a["action"], a["actor"]) for a in audit if a["action"] == "expire"] == [("expire", "retention policy")]


async def test_a_policy_that_cannot_be_read_keeps_everything() -> None:
    def answer(status: int, value: object) -> PlatformRetention:
        body = {"success": True, "data": {"key": "memoryRetentionDays", "value": value}}
        transport = httpx.MockTransport(lambda _: httpx.Response(status, json=body))
        http = httpx.AsyncClient(transport=transport, base_url="http://platform")
        return PlatformRetention(ServiceClient(http, dev_service_signer(), "agents", "platform", tenant=lambda: "acme"))

    assert await answer(200, 30).days() == 30.0
    assert [await answer(s, v).days() for s, v in [(500, 30), (403, 30), (200, None), (200, True)]] == [None] * 4
