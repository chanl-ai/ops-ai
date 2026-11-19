"""A workflow's runs a page at a time in SQL (`GraphStore.thread_page`, `run_events`), by failure mode: another team's
or tenant's run on the page, in the total or in the counts when the database lets every team through; runs of one
update time repeated or lost between pages; a status filter that drops the statuses no label names. On PostgreSQL
and SQL Server."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.graphs import GraphStore, graph_runs, graph_threads
from ops_agents.store.tenancy import tenant_tx
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.team_scope import acting_as
from ops_store.testing import DATABASES, NO_SQL_SERVER, sql_server_schema

from ..conftest import emptied

AT = "2026-11-16T09:00:00.000Z"
ROOT = Path(__file__).resolve().parents[2]
TEAM, OTHER = "team_cards", "team_lending"
LABELS = {"done": "completed", "interrupted": "waiting_review"}


@pytest.fixture(scope="module", params=DATABASES)
def url(request: pytest.FixtureRequest) -> Iterator[str]:
    if request.param == "postgresql":
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        yield Settings().database_url
        return
    with sql_server_schema("agents", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")) as u:
        if u is None:
            pytest.skip(NO_SQL_SERVER)
        yield u


@pytest.fixture
async def engine(url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(url)
    if url.startswith("postgresql"):
        # The Postgres database outlives one test, and these rows use fixed ids another store test also inserts.
        await emptied(e)
    yield e
    await e.dispose()


async def _run(e: AsyncEngine, thread_id: str, status: str, *, team: str = TEAM) -> None:
    """A thread of the `refunds` workflow and one run whose journal names the thread."""
    async with tenant_tx(e) as c:
        values: dict[str, object] = {
            "graph": "refunds",
            "meta": {},
            "team_id": team,
            "created_at": AT,
            "updated_at": AT,
        }
        await c.execute(graph_threads.insert().values(id=thread_id, status=status, **values))
        events = [{"event": "node_start", "node": thread_id}]
        await c.execute(
            graph_runs.insert().values(
                id=f"run_{thread_id}",
                thread_id=thread_id,
                kind="input",
                status="done",
                events=events,
                created_at=AT,
                team_id=team,
            )
        )


async def test_the_page_total_counts_and_journals_hold_the_team_and_page_by_the_key(engine: AsyncEngine) -> None:
    tenant, stranger = f"t_{uuid4().hex[:10]}", f"t_{uuid4().hex[:10]}"
    with isolation.scope(tenant, TEAM):
        for thread_id, status in (("th_a", "done"), ("th_b", "interrupted"), ("th_c", "idle"), ("th_d", "done")):
            await _run(engine, thread_id, status)
    with isolation.scope(tenant, OTHER):
        await _run(engine, "th_theirs", "done", team=OTHER)
    with isolation.scope(stranger, TEAM):
        await _run(engine, "th_stranger", "done")
    store = GraphStore(engine)
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    with (
        isolation.tenant_wide("a test reads a workflow's runs with every team let through", tenant_id=tenant),
        acting_as(TEAM),
    ):
        first, total, counted = await store.thread_page("refunds", LABELS, "running", [], offset=0, limit=2)
        second, _, _ = await store.thread_page("refunds", LABELS, "running", [], offset=2, limit=2)
        kept, kept_total, kept_counts = await store.thread_page(
            "refunds", LABELS, "running", ["running", "waiting_review"], offset=0, limit=10
        )
        journals = await store.run_events(["th_a", "th_theirs", "th_stranger"])
    # Equal update times page by the id; no other team's or tenant's run on a page, in the total or the counts.
    assert [t.id for t in first + second] == ["th_a", "th_b", "th_c", "th_d"]
    assert (total, counted) == (4, {"completed": 2, "waiting_review": 1, "running": 1})
    # A status no label names is `running`, and the counts are over every run, not the kept ones.
    assert ([t.id for t in kept], kept_total, kept_counts) == (["th_b", "th_c"], 2, counted)
    assert [(j.thread_id, j.events) for j in journals] == [("th_a", [{"event": "node_start", "node": "th_a"}])]
