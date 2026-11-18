"""The agents list a page at a time in SQL (`AgentRegistry.page`), by failure mode: another team's agents on the page
when the database lets every team through; agents with one name repeated or lost between pages, a total that counts
rows the page does not hold, or a page past the end answering nothing; the busiest agent not first when sorted by its
threads of the last day, or a builder's test thread counted; availability counted or filtered wrongly; the tenant's
owners asked for more agents than SQL Server takes parameters in one statement."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.agent_registry import AgentRegistry, registry_agent_versions, registry_agents
from ops_agents.store.graphs import GraphStore
from ops_agents.store.tenancy import tenant_tx
from ops_service_kit.http import Json
from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.team_scope import acting_as

AT = "2026-11-16T09:00:00.000Z"
SINCE = "2026-11-15T09:00:00.000Z"
TEAM, OTHER = "team_cards", "team_lending"


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:10]}"


async def _agent(e: AsyncEngine, agent_id: str, name: str, *, team: str = TEAM, published: bool = False) -> None:
    spec = {"name": name, "role": f"{name} role", "model": "m"}
    async with tenant_tx(e) as c:
        await c.execute(
            registry_agents.insert().values(
                id=agent_id,
                slug=agent_id,
                team_id=team,
                version=1,
                published_version=1 if published else None,
                paused=False,
                created_at=AT,
                updated_at=AT,
            )
        )
        await c.execute(
            registry_agent_versions.insert().values(
                agent_id=agent_id, version=1, spec=spec, digest="d", note="", changes=[], saved_at=AT, saved_by="t"
            )
        )


async def _page(e: AsyncEngine, **params: Any) -> tuple[list[str], dict[str, Any]]:
    listed = await AgentRegistry(e).page(ListParams(**params), since=SINCE)
    return [str(r["id"]) for r in listed["data"]], {"pagination": listed["pagination"], "facets": listed["facets"]}


async def test_the_page_holds_the_acting_team_when_the_policy_lets_every_team_through(
    engine: AsyncEngine, tenant: str
) -> None:
    with isolation.scope(tenant, TEAM):
        await _agent(engine, "ag_mine", "Card desk")
    with isolation.scope(tenant, OTHER):
        await _agent(engine, "ag_theirs", "Loan desk", team=OTHER)
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    with isolation.tenant_wide("a test reads the agents list with every team let through", tenant_id=tenant):
        with acting_as(TEAM):
            mine, _ = await _page(engine)
        with acting_as(OTHER):
            theirs, _ = await _page(engine)
    assert (mine, theirs) == (["ag_mine"], ["ag_theirs"])


async def test_equal_names_each_appear_once_across_pages_and_past_the_end_answers_the_last_page(
    engine: AsyncEngine, tenant: str
) -> None:
    with isolation.scope(tenant, TEAM):
        for agent_id in ("ag_c", "ag_a", "ag_b"):
            await _agent(engine, agent_id, "Desk")
        seen: list[str] = []
        for page_no in (1, 2, 3):
            ids, _ = await _page(engine, page=page_no, page_size=1, sort_order="asc")
            seen += ids
        past, shape = await _page(engine, page=9, page_size=2)
    assert seen == ["ag_a", "ag_b", "ag_c"]
    assert (past, shape["pagination"]["page"], shape["pagination"]["total"]) == (["ag_c"], 2, 3)


async def test_sorted_by_tasks_the_busiest_is_first_and_a_test_thread_is_not_counted(
    engine: AsyncEngine, tenant: str
) -> None:
    graphs = GraphStore(engine)
    with isolation.scope(tenant, TEAM):
        for agent_id in ("ag_quiet", "ag_busy", "ag_tested"):
            await _agent(engine, agent_id, agent_id)
        threads: list[tuple[str, Json]] = [
            ("agent:ag_busy", {}),
            ("agent_wrapper", {"agentId": "ag_busy"}),
            ("agent:ag_quiet", {}),
            ("agent:ag_tested", {"test": True}),
            ("agent_wrapper", {"agentId": "ag_tested", "test": True}),
        ]
        for i, (graph, meta) in enumerate(threads):
            await graphs.create_thread(f"th_{tenant}_{i}", graph, meta, TEAM, AT)
        await graphs.create_thread(f"th_{tenant}_old", "agent:ag_tested", {}, TEAM, "2026-11-01T00:00:00.000Z")
        listed = await AgentRegistry(engine).page(ListParams(sort_by="tasks24h", sort_order="desc"), since=SINCE)
    assert [(r["id"], r["tasks_24h"]) for r in listed["data"]] == [("ag_busy", 2), ("ag_quiet", 1), ("ag_tested", 0)]


async def test_availability_is_counted_across_the_team_and_filters_the_page(engine: AsyncEngine, tenant: str) -> None:
    with isolation.scope(tenant, TEAM):
        await _agent(engine, "ag_live", "Live desk", published=True)
        await _agent(engine, "ag_draft", "Draft desk")
        ids, shape = await _page(engine, filters={"availability": ["published"]})
    assert ids == ["ag_live"]
    assert shape["facets"]["availability"] == {"published": 1, "not_published": 1}


async def test_owners_are_answered_for_more_agents_than_one_statement_takes(engine: AsyncEngine, tenant: str) -> None:
    with isolation.scope(tenant, TEAM):
        await _agent(engine, f"ag_{tenant}_a", "A")
    with isolation.scope(tenant, OTHER):
        await _agent(engine, f"ag_{tenant}_b", "B", team=OTHER)
    with isolation.scope(f"{tenant}x", TEAM):
        await _agent(engine, f"ag_{tenant}_c", "C")
    asked = {f"ag_{tenant}_{n}" for n in ("a", "b", "c")} | {f"ag_missing_{i}" for i in range(2500)}
    with isolation.scope(tenant, TEAM):
        owners = [await AgentRegistry(engine).tenant_owners(ids) for ids in (asked, {f"ag_{tenant}_b"})]
    assert owners == [{f"ag_{tenant}_a": TEAM, f"ag_{tenant}_b": OTHER}, {f"ag_{tenant}_b": OTHER}]
