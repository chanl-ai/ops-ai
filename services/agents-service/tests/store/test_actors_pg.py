"""Who started a run, named (api/actors.py), on PostgreSQL, where tenant reads run under the tenant role: a run started
through an agent made the Runs list and Activity answer 500, because the agent's name was read under a role that may
not read the registry. Runs on the migrated test database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.actors import actors
from ops_agents.store.agent_registry import registry_agent_versions, registry_agents
from ops_agents.store.tenancy import tenant_scope


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_a_person_asking_through_an_agent_names_the_agent(engine: AsyncEngine) -> None:
    agent = f"ag_{uuid4().hex[:10]}"
    async with engine.begin() as c:
        await c.execute(
            registry_agents.insert().values(
                id=agent, slug=agent, team_id="team_ops", version=1, paused=False, created_at="n", updated_at="n"
            )
        )
        await c.execute(
            registry_agent_versions.insert().values(
                agent_id=agent,
                version=1,
                spec={"name": "Advisor's Helper"},
                digest="d",
                note="",
                changes=[],
                saved_at="n",
                saved_by="b",
            )
        )
    rt: Any = SimpleNamespace(db=engine)
    raw = f"james@northfield.example via agent:{agent}"
    with tenant_scope(f"t-{uuid4().hex[:6]}"):
        who = await actors(rt, [raw])
    assert who[raw]["via"] == {"kind": "agent", "id": agent, "name": "Advisor's Helper"}, who
