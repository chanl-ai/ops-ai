"""Tenant isolation at rest, on the PostgreSQL test database, by failure mode: a tenant reading another's run rows,
a statement with no tenant reading anything, a request running as the role that bypasses RLS, the bypass reachable
from outside the two loops, two threads of one sweep sharing a tenant, and checkpoints stored under the wrong
tenant."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict
from uuid import uuid4

import pytest
import sqlalchemy as sa
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.events import EventLog, thread_events
from ops_agents.store.graphs import GraphStore, graph_runs, graph_threads
from ops_agents.store.reviews import ReviewStore, review_approvals, review_decisions
from ops_agents.store.tenancy import (
    SYSTEM_ROLE,
    TENANT_ROLE,
    NoTenantError,
    current_tenant,
    tenant_scope,
    tenant_tx,
)
from ops_checkpointer import open_saver
from ops_service_kit.ids import new_id, now_iso

SRC = Path(__file__).parents[2] / "src" / "ops_agents"
TABLES = (graph_threads, graph_runs, thread_events, review_decisions, review_approvals)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def seed(engine: AsyncEngine, tenant: str) -> str:
    """One thread with a run, an event, a decision and an approval, written as `tenant`."""
    store, thread_id = GraphStore(engine), new_id("gth")
    with tenant_scope(tenant):
        await store.create_thread(thread_id, "g", {}, "team_a", now_iso())
        await store.start_run(new_id("run"), thread_id, "input", now_iso())
        await EventLog(engine).append(thread_id=thread_id, team_id="team_a", run_id=None, type_="started")
        reviews = ReviewStore(engine)
        await reviews.record_decision(thread_id, "d1", decision="approved", reason=None, by="x", review={})
        await reviews.approve(thread_id, "step", "x", "h", distinct=False)
    return thread_id


async def visible(engine: AsyncEngine, tenant: str, table: sa.Table, thread_id: str) -> int:
    """Counts the thread's rows as `tenant` with no tenant in the WHERE clause, so only the policy can filter."""
    with tenant_scope(tenant):
        async with tenant_tx(engine) as c:
            key = table.c.id if table is graph_threads else table.c.thread_id
            q = sa.select(sa.func.count()).select_from(table).where(key == thread_id)
            return int((await c.execute(q)).scalar_one())


async def test_a_tenant_sees_only_its_own_rows_in_every_run_table(engine: AsyncEngine) -> None:
    a, b = f"a-{uuid4().hex[:8]}", f"b-{uuid4().hex[:8]}"
    thread_a = await seed(engine, a)
    for table in TABLES:
        assert await visible(engine, a, table, thread_a) == 1, table.name
        assert await visible(engine, b, table, thread_a) == 0, table.name
    with tenant_scope(b):
        assert await GraphStore(engine).thread(thread_a) is None


async def test_a_write_naming_another_tenant_is_refused_by_the_policy(engine: AsyncEngine) -> None:
    with tenant_scope("a-writer"):
        async with tenant_tx(engine) as c:
            with pytest.raises(ProgrammingError, match="row-level security"):
                await c.execute(
                    graph_threads.insert().values(
                        id=new_id("gth"),
                        graph="g",
                        meta={},
                        team_id="t",
                        created_at=now_iso(),
                        updated_at=now_iso(),
                        status="idle",
                        tenant_id="someone-else",
                    )
                )


async def test_no_tenant_reads_nothing(engine: AsyncEngine) -> None:
    thread_a = await seed(engine, f"a-{uuid4().hex[:8]}")
    with pytest.raises(NoTenantError):
        current_tenant()
    with pytest.raises(NoTenantError):
        await GraphStore(engine).thread(thread_a)
    # Below the store: the tenant role with app.tenant_id unset sees no row at all.
    async with engine.begin() as c:
        await c.execute(sa.text(f"SET LOCAL ROLE {TENANT_ROLE}"))
        assert (await c.execute(sa.select(sa.func.count()).select_from(graph_threads))).scalar_one() == 0


async def test_requests_run_as_the_tenant_role_which_cannot_bypass_rls(engine: AsyncEngine) -> None:
    with tenant_scope("a-role"):
        async with tenant_tx(engine) as c:
            assert (await c.execute(sa.text("select current_user"))).scalar_one() == TENANT_ROLE
    async with engine.connect() as c:
        q = sa.text("select rolname, rolbypassrls from pg_roles where rolname in (:t, :s)")
        roles = dict((await c.execute(q, {"t": TENANT_ROLE, "s": SYSTEM_ROLE})).all())
    assert roles == {TENANT_ROLE: False, SYSTEM_ROLE: True}


def test_only_the_two_loops_reach_past_rls() -> None:
    """`tenant_of` is the one read under the bypass role; only the sweeper and timer poller may call it."""
    callers: set[str] = set()
    system_users: set[str] = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and node.attr == "tenant_of":
                callers.add(path.relative_to(SRC).as_posix())
            if isinstance(node, ast.Name) and node.id == "system_tx":
                system_users.add(path.relative_to(SRC).as_posix())
    assert callers == {"api/tenant_tasks.py"}
    assert system_users == {"store/graphs.py"}
    tasks_users = {p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py") if "as_thread_tenant" in p.read_text()} - {
        "api/tenant_tasks.py"
    }
    assert tasks_users == {"api/sweeper.py", "api/timers.py"}


async def test_two_threads_worked_by_one_sweep_each_get_their_own_tenant(engine: AsyncEngine) -> None:
    from ops_agents.api.tenant_tasks import as_thread_tenant  # noqa: PLC0415

    a, b = f"a-{uuid4().hex[:8]}", f"b-{uuid4().hex[:8]}"
    thread_a, thread_b = await seed(engine, a), await seed(engine, b)

    async def seen() -> str:
        await asyncio.sleep(0.05)  # both tasks are alive at once
        return current_tenant()

    rt: Any = SimpleNamespace(graph_store=GraphStore(engine), graphs={"g": object()}, leases=object())
    got = await asyncio.gather(as_thread_tenant(rt, thread_a, seen), as_thread_tenant(rt, thread_b, seen))
    assert got == [a, b]
    with pytest.raises(NoTenantError):
        current_tenant()  # the loop's own context never took a tenant


class S(TypedDict):
    n: int


async def test_one_compiled_graph_stores_each_tenants_checkpoints_under_that_tenant(database_url: str) -> None:
    a, b = f"a-{uuid4().hex[:8]}", f"b-{uuid4().hex[:8]}"
    builder: Any = StateGraph(S)

    def inc(state: S) -> S:
        return {"n": state["n"] + 1}

    builder.add_node("inc", inc)
    builder.add_edge(START, "inc")
    builder.add_edge("inc", END)
    async with open_saver(database_url, tenant_id=current_tenant, team_id="local") as saver:
        graph: Any = builder.compile(checkpointer=saver)
        thread_a, thread_b = f"t-{uuid4().hex}", f"t-{uuid4().hex}"
        with tenant_scope(a):
            await graph.ainvoke({"n": 0}, {"configurable": {"thread_id": thread_a}})
        with tenant_scope(b):
            await graph.ainvoke({"n": 0}, {"configurable": {"thread_id": thread_b}})
            assert (await graph.aget_state({"configurable": {"thread_id": thread_a}})).values == {}
        with tenant_scope(a):
            assert (await graph.aget_state({"configurable": {"thread_id": thread_a}})).values == {"n": 1}
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as c:  # the compose superuser, past RLS: what is stored where
            q = sa.text(
                "select thread_id, min(tenant_id), count(*) from ops_checkpoints where thread_id in (:a, :b) group by 1"
            )
            stored = {r[0]: (r[1], r[2] > 0) for r in await c.execute(q, {"a": thread_a, "b": thread_b})}
    finally:
        await engine.dispose()
    assert stored == {thread_a: (a, True), thread_b: (b, True)}
