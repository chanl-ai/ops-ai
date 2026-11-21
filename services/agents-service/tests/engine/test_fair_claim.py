"""The fair claim on engine_work and the paged run reconciler, by failure mode: one team at its cap holds back another;
a run waiting for a person takes one of its team's slots; two workers take one row, or a team passes its cap when they
claim at once (on SQL Server too); the reconciler sends a statement past SQL Server's 2,100 parameters."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import WorkQueue, reconciler
from ops_engine.store.clock import now_iso
from ops_engine.store.tables import engine_runs, engine_work
from ops_store.dialect import db_epoch
from ops_store.testing import DATABASES, NO_SQL_SERVER, sql_server_schema

SQL_SERVER_PARAMETERS = 2100


@pytest.fixture(scope="module", params=DATABASES)
def url(request: pytest.FixtureRequest) -> Iterator[str]:
    if request.param == "postgresql":
        yield request.getfixturevalue("database_url")
        return
    with sql_server_schema("agents", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")) as ms:
        if ms is None:
            pytest.skip(NO_SQL_SERVER)
        yield ms


@pytest.fixture
async def engine(url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(url, pool_size=10)
    yield e
    await e.dispose()


@asynccontextmanager
async def in_tenant(engine: AsyncEngine, tenant: str) -> AsyncGenerator[AsyncConnection]:
    """A transaction inside `tenant`: SQL Server's row-level security refuses a write that names no tenant."""
    with tenant_scope(tenant):
        async with EngineTransactions(engine).tenant_tx() as c:
            yield c


def ids() -> tuple[str, str]:
    """A tenant and an engine build of the test's own, so no other test's rows are claimed."""
    return f"t-{uuid4().hex[:8]}", f"b-{uuid4().hex[:8]}"


async def rows(
    engine: AsyncEngine, tenant: str, build: str, *teams: str, status: str = "queued", lease_s: float | None = None
) -> list[int]:
    """One due work row per team named, oldest first; `lease_s` gives each a live claim that long."""
    out: list[int] = []
    async with in_tenant(engine, tenant) as c:
        now = (await c.execute(sa.select(db_epoch()))).scalar_one()
        for team in teams:
            values: dict[str, Any] = {
                "tenant_id": tenant,
                "team_id": team,
                "run_id": f"wfrun_{uuid4().hex[:12]}",
                "kind": "start",
                "dedupe_key": uuid4().hex,
                "status": status,
                "build": build,
                "available_at": 0.0,
                "attempts": 0,
                "lapses": 0,
                "created_at": now_iso(),
            }
            if lease_s is not None:
                values |= {"claimed_by": "w-live", "lease_expires_at": float(now) + lease_s}
            out.append(
                int((await c.execute(engine_work.insert().values(**values).returning(engine_work.c.id))).scalar_one())
            )
    return out


def queue(engine: AsyncEngine, build: str, cap: int | None, owner: str = "w1") -> WorkQueue:
    return WorkQueue(EngineTransactions(engine), owner, ttl=30, build=build, team_cap=cap)


async def test_one_team_at_its_cap_does_not_hold_back_another(engine: AsyncEngine) -> None:
    tenant, build = ids()
    a1, _a2, _a3, b1 = await rows(engine, tenant, build, "team_a", "team_a", "team_a", "team_b")
    q = queue(engine, build, cap=1)
    taken = [await q.claim() for _ in range(3)]
    # team_a's older rows wait behind its one running row; team_b's newer row is claimed next.
    assert [t.id if t else None for t in taken] == [a1, b1, None]


async def test_a_run_waiting_for_a_person_takes_no_slot(engine: AsyncEngine) -> None:
    tenant, build = ids()
    await rows(engine, tenant, build, "team_a", status="claimed", lease_s=60)
    # A run parked on a review: its run reads Waiting and its work row is done, so nothing of it is claimed.
    parked = (await rows(engine, tenant, build, "team_a", status="done"))[0]
    async with in_tenant(engine, tenant) as c:
        run_id = (await c.execute(sa.select(engine_work.c.run_id).where(engine_work.c.id == parked))).scalar_one()
        at = now_iso()
        await c.execute(
            engine_runs.insert().values(
                id=run_id,
                tenant_id=tenant,
                team_id="team_a",
                workflow_id="wf",
                version=1,
                digest="d",
                run_key=run_id,
                mode="live",
                status="waiting",
                created_by="a@x",
                created_at=at,
                updated_at=at,
            )
        )
    (queued,) = await rows(engine, tenant, build, "team_a")
    assert await queue(engine, build, cap=1).claim() is None, "one row runs: team_a is at a cap of 1"
    got = await queue(engine, build, cap=2).claim()
    assert got is not None and got.id == queued, "the waiting run took team_a's second slot"


async def test_two_workers_never_take_one_row_and_a_team_keeps_to_its_cap(engine: AsyncEngine) -> None:
    tenant, build = ids()
    await rows(engine, tenant, build, *["team_a"] * 6, *["team_b"] * 2)
    got = await asyncio.gather(*(queue(engine, build, cap=2, owner=f"w{i}").claim() for i in range(8)))
    taken = [g.id for g in got if g is not None]
    assert taken and len(taken) == len(set(taken)), taken
    async with in_tenant(engine, tenant) as c:
        held = dict(
            (
                await c.execute(
                    sa.select(engine_work.c.team_id, sa.func.count())
                    .where(engine_work.c.build == build, engine_work.c.status == "claimed")
                    .group_by(engine_work.c.team_id)
                )
            ).all()
        )
    assert held.get("team_a", 0) <= 2 and held.get("team_b", 0) <= 2, held


async def test_the_reconciler_never_sends_past_sql_servers_parameter_limit(engine: AsyncEngine) -> None:
    tenant, _ = ids()
    many = SQL_SERVER_PARAMETERS + 100
    quiet = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    runs = [
        {
            "id": f"wfrun_{tenant}_{n:05d}",
            "tenant_id": tenant,
            "team_id": "team_a",
            "workflow_id": "wf",
            "version": 1,
            "digest": "d",
            "run_key": f"{tenant}-{n}",
            "mode": "live",
            "status": "queued",
            "created_by": "a@x",
            "created_at": quiet,
            "updated_at": quiet,
        }
        for n in range(many)
    ]
    async with in_tenant(engine, tenant) as c:
        # 150 rows of 12 values: under the limit on the way in too.
        for start in range(0, many, 150):
            await c.execute(engine_runs.insert(), runs[start : start + 150])
    biggest = 0

    def count(_c: Any, _cur: Any, _sql: str, parameters: Any, _ctx: Any, executemany: bool) -> None:
        nonlocal biggest
        if not executemany:
            biggest = max(biggest, len(parameters or ()))

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        found = await reconciler.find(EngineTransactions(engine))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)
        async with in_tenant(engine, tenant) as c:
            # Ended, so no other test's reconciler pass finds them; the tenant's role may not delete runs.
            await c.execute(engine_runs.update().where(engine_runs.c.tenant_id == tenant).values(status="cancelled"))
    # Every one of them is found (each has nothing behind it), and no statement carried them all at once.
    assert len([f for f in found if f.tenant_id == tenant]) == many
    assert biggest < SQL_SERVER_PARAMETERS, biggest
