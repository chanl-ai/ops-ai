"""Which agents cite a knowledge base, read in SQL, by failure mode: a tenant-wide read with a team acting naming
another team's agent (the query's team predicate and the team policy each stand alone there); a base not asked about
read; and a newer unpublished version counted instead of the one an agent serves. On the PostgreSQL test database
migrated to head, as ops_runtime_tenant."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.agent_registry import AgentRegistry
from ops_agents.store.knowledge_citations import KnowledgeCitations
from ops_agents.store.tenancy import OWNER
from ops_service_kit.http import Json
from ops_store import isolation
from ops_store.team_scope import acting_as


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_a_team_reads_only_its_own_agents_citing_the_bases_asked(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    reg = AgentRegistry(engine)
    made: dict[str, str] = {}
    for key, team, collections in (
        ("served", "team_a", ["kb_x"]),
        ("other", "team_a", ["kb_y"]),
        ("b", "team_b", ["kb_x"]),
    ):
        with isolation.scope(tenant, team), acting_as(team):
            # A whole spec (a role too): the agent is published, and the catalogue serves it to later tests.
            spec: Json = {"name": f"Agent {key}", "role": "Answers questions", "collections": [*collections]}
            made[key] = await reg.create(spec, by="maya@x.example", team_id=team, published=True)
    with isolation.scope(tenant, "team_a"), acting_as("team_a"):
        # A newer draft that drops the base: the agent still serves version 1, which cites it.
        await reg.save(
            made["served"],
            {"name": "Agent served", "role": "Answers questions", "collections": []},
            by="maya@x.example",
        )
    store = KnowledgeCitations(engine)
    # The tenant-wide scope opens every team's rows to the policy, so the query's own predicates are what stand.
    with isolation.tenant_wide(OWNER, tenant_id=tenant), acting_as("team_a"):
        ours = await store.citing("team_a", ["kb_x"])
        theirs = await store.citing("team_b", ["kb_x"])
        every = await store.citing("team_a", None)
    assert [(c.agent_id, c.collections) for c in ours] == [(made["served"], ("kb_x",))], ours
    assert theirs == [], theirs
    assert sorted(c.agent_id for c in every) == sorted([made["served"], made["other"]]), every
