"""The threads list a page at a time in SQL (`threads_page`), by failure mode: another team's thread on the page or in
the total when the database lets every team through; a thread the reader may not read counted in the total; threads
of one update time repeated or lost between pages. Who reads which thread is pinned through the route
(`tests/api/test_thread_readers.py`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.graphs import graph_threads
from ops_agents.store.tenancy import tenant_tx
from ops_agents.store.thread_list import ThreadReader, threads_page
from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.team_scope import acting_as

AT = "2026-11-16T09:00:00.000Z"
TEAM, OTHER = "team_cards", "team_lending"
VERA = ThreadReader(graphs=None, chat="own", email="vera@harborpine.example", name="vera")


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:10]}"


async def _thread(e: AsyncEngine, thread_id: str, *, team: str = TEAM, meta: dict[str, Any] | None = None) -> None:
    meta = meta or {}
    async with tenant_tx(e) as c:
        await c.execute(
            graph_threads.insert().values(
                id=thread_id,
                graph="agent_wrapper" if meta else "refunds",
                meta=meta,
                team_id=team,
                owner=meta.get("ownerEmail"),
                created_at=AT,
                updated_at=AT,
                status="idle",
            )
        )


async def _listed(e: AsyncEngine, reader: ThreadReader = VERA, **params: Any) -> tuple[list[str], int]:
    page = await threads_page(e, ListParams(**params), reader)
    return [str(r["id"]) for r in page["data"]], page["pagination"]["total"]


async def test_the_page_and_total_hold_the_acting_team_when_the_policy_lets_every_team_through(
    engine: AsyncEngine, tenant: str
) -> None:
    with isolation.scope(tenant, TEAM):
        await _thread(engine, "th_mine")
    with isolation.scope(tenant, OTHER):
        await _thread(engine, "th_theirs", team=OTHER)
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    with (
        isolation.tenant_wide("a test reads the threads list with every team let through", tenant_id=tenant),
        acting_as(TEAM),
    ):
        listed = await _listed(engine)
    assert listed == (["th_mine"], 1)


async def test_unreadable_threads_are_not_counted_and_equal_update_times_page_by_the_key(
    engine: AsyncEngine, tenant: str
) -> None:
    with isolation.scope(tenant, TEAM):
        for thread_id in ("th_c", "th_a", "th_b"):
            await _thread(engine, thread_id)
        await _thread(engine, "th_vera", meta={"chat": True, "ownerEmail": "vera@harborpine.example"})
        await _thread(engine, "th_otto", meta={"chat": True, "ownerEmail": "otto@harborpine.example"})
        pages = [await _listed(engine, page=p, page_size=2) for p in (1, 2, 3)]
    # A page past the end answers the last page (`page_window`).
    assert pages == [(["th_vera", "th_c"], 4), (["th_b", "th_a"], 4), (["th_b", "th_a"], 4)]
