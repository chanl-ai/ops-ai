"""The workspace's memory retention and clean-up (c-206, c-557), by failure mode: an expired memory survives, a kept
one is deleted, the deletion is not audited, a policy that cannot be read deletes anything, a forgotten memory keeps
its text past its grace or loses it within it, a suggestion nobody answered stays for ever, a conflict is settled
without the person, or a pass leaves no record on the Background page."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import sqlalchemy as sa

from ops_agents.api.memory_retention import PlatformRetention, expire_memories
from ops_agents.api.runs import graph_store
from ops_agents.store.background import background_jobs
from ops_agents.store.memories import CONFLICT, FORGOTTEN, SUGGESTED, agent_memories
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


def stamp(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def set_rows(rt: Any, key: str, **values: Any) -> None:
    with tenant_scope(TENANT):
        async with tenant_tx(graph_store(rt).engine) as c:
            await c.execute(agent_memories.update().where(agent_memories.c.key == key).values(**values))


async def kept(rt: Any) -> list[tuple[str, str]]:
    m = agent_memories.c
    with tenant_scope(TENANT):
        async with tenant_tx(graph_store(rt).engine) as c:
            return [tuple(r) for r in (await c.execute(sa.select(m.key, m.status).order_by(m.key))).all()]


async def test_clean_up_erases_what_was_forgotten_or_left_unanswered_and_settles_no_conflict(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    for said in ("timezone is Eastern", "city is Leeds", "branch is York", "team is Cards", "desk is Four"):
        await say(c, await chat(c, VIEWER), f"Noted for later: my {said}.", VIEWER)
    await set_rows(rt, "timezone", status=FORGOTTEN, erase_after=stamp(1))
    await set_rows(rt, "city", status=FORGOTTEN, erase_after=stamp(-5))
    await set_rows(rt, "branch", status=SUGGESTED, created_at=stamp(15))
    await set_rows(rt, "team", status=SUGGESTED, created_at=stamp(3))
    await set_rows(rt, "desk", status=CONFLICT, created_at=stamp(60))
    assert await expire_memories(rt, Days(None), NOW) == 2, "no retention policy is needed for either"
    assert await kept(rt) == [("city", FORGOTTEN), ("desk", CONFLICT), ("team", SUGGESTED)]
    audit = (await c.get(f"{MINE}/export", headers=VIEWER)).json()["data"]["audit"]
    assert sorted(a["action"] for a in audit if a["actor"] == "retention policy") == ["erase", "erase"]
    j = background_jobs.c
    with tenant_scope(TENANT):
        async with tenant_tx(graph_store(rt).engine) as conn:
            jobs = list((await conn.execute(sa.select(j.summary).where(j.process == "memory_cleanup"))).scalars())
    assert jobs[-1:] == ["1 erased, 1 unanswered suggestions erased, 0 past retention deleted"], jobs
