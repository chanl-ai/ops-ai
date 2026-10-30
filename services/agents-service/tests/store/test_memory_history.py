"""Memory records with history (c-557, c-563), by failure mode: two chats of one person saving the same key at once
both stay in use (a thread's lease serialises one thread only, so the store serialises a person's saves itself); an old
memory is never found because only recent rows are searched; a word matches inside another word. Each runs on the
migrated PostgreSQL test database and on SQL Server: a scratch database on OPS_MSSQL_SERVER (host,port) with
MSSQL_SA_PASSWORD holding the memory tables, skipped when they are unset (docs/deploy/fly.md, SQL Server test
machine)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store import memories as memories_module
from ops_agents.store.base import metadata
from ops_agents.store.memories import ACTIVE, Memories, agent_memories, memory_audit
from ops_agents.store.tenancy import current_tenant, tenant_scope, tenant_tx
from ops_service_kit.ids import new_id, now_iso

FULL_TEXT_MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0085_memory_full_text.py"
ODBC = {"driver": "ODBC Driver 18 for SQL Server", "TrustServerCertificate": "yes"}


def mssql(database: str, driver: str = "mssql+aioodbc") -> sa.URL | None:
    server, password = os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")
    if not server or not password:
        return None
    host, port = server.split(",")
    return sa.URL.create(driver, "sa", password, host, int(port), database, ODBC)


def memory_tables(url: sa.URL) -> None:
    """The memory tables from the store's metadata, with the primary key named as the migrations name it, and 0085's
    full-text index. The agents chain is not run: it stops at 0004_checkpointer_ops_checkpoints on SQL Server (an
    unquoted reserved word) until the agents migrations run there."""
    spec = importlib.util.spec_from_file_location("memory_full_text", FULL_TEXT_MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    e = sa.create_engine(url.set(drivername="mssql+pyodbc"), isolation_level="AUTOCOMMIT")
    try:
        metadata.create_all(e, tables=[agent_memories, memory_audit])
        with e.connect() as c:
            pk = c.execute(
                sa.text(
                    "SELECT name FROM sys.key_constraints "
                    "WHERE type = 'PK' AND parent_object_id = OBJECT_ID('agent_memories')"
                )
            ).scalar_one()
            c.execute(sa.text(f"EXEC sp_rename N'dbo.{pk}', N'agent_memories_pkey', N'OBJECT'"))
            c.execute(sa.text(migration.MSSQL_FULL_TEXT))
    finally:
        e.dispose()


@pytest.fixture(scope="module")
def mssql_url() -> Iterator[sa.URL]:
    """A scratch SQL Server database holding the memory tables, dropped afterwards."""
    master = mssql("master", "mssql+pyodbc")
    if master is None:
        pytest.skip("set OPS_MSSQL_SERVER and MSSQL_SA_PASSWORD to run on SQL Server")
    name = f"ops_memory_{uuid4().hex[:8]}"
    admin = sa.create_engine(master, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(sa.text(f"CREATE DATABASE [{name}]"))
    url = mssql(name)
    assert url is not None
    try:
        memory_tables(url)
        yield url
    finally:
        with admin.connect() as c:
            c.execute(sa.text(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE"))
            c.execute(sa.text(f"DROP DATABASE [{name}]"))
        admin.dispose()


@pytest.fixture(params=["postgresql", "mssql"])
def db_url(request: pytest.FixtureRequest) -> str | sa.URL:
    """Each database the store runs on; both fixtures migrate synchronously, so they are asked for outside the loop."""
    return request.getfixturevalue("database_url" if request.param == "postgresql" else "mssql_url")


@pytest.fixture
async def engine(db_url: str | sa.URL) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(db_url, pool_size=12)
    yield e
    await e.dispose()


async def eventually(find: Callable[[], Awaitable[list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    """What `find` returns once it finds anything, within 30 s: SQL Server fills a full-text index in the background."""
    for _ in range(60):
        if found := await find():
            return found
        await asyncio.sleep(0.5)
    return []


async def test_saves_of_one_key_from_two_chats_at_once_leave_one_in_use(engine: AsyncEngine) -> None:
    store = Memories(engine)

    async def save(n: int) -> None:
        await store.save(
            team_id="team_ops",
            agent_id="",
            person="p@x",
            kind="preference",
            key="answer style",
            value=f"style {n}",
            confidence=1.0,
            source="extraction",
            thread_id=f"th_{n}",
        )

    with tenant_scope(f"m-{uuid4().hex[:8]}"):
        await asyncio.gather(*(save(n) for n in range(10)))
        m = agent_memories.c
        async with tenant_tx(engine) as c:
            statuses = list((await c.execute(sa.select(m.status).where(m.person == "p@x"))).scalars())
    assert len(statuses) == 10, statuses
    assert statuses.count(ACTIVE) == 1, statuses


async def keep(store: Memories, key: str, value: str, *, created_at: str | None = None) -> None:
    row = await store.save(
        team_id="team_ops",
        agent_id="",
        person="p@x",
        kind="fact",
        key=key,
        value=value,
        confidence=0.9,
        source="extraction",
        thread_id=None,
    )
    if created_at:
        async with tenant_tx(store.engine) as c:
            m = agent_memories.c
            await c.execute(agent_memories.update().where(m.id == row["id"]).values(created_at=created_at))


async def seed_notes(store: Memories, count: int) -> None:
    now = now_iso()
    rows = [
        {
            "id": new_id("mem"),
            "tenant_id": current_tenant(),
            "team_id": "team_ops",
            "agent_id": "",
            "person": "p@x",
            "kind": "fact",
            "key": f"note {n}",
            "value": f"Routine branch note number {n} about the weekly rota",
            "confidence": 0.9,
            "source": "extraction",
            "created_at": now,
        }
        for n in range(count)
    ]
    async with tenant_tx(store.engine) as c:
        await c.execute(agent_memories.insert(), rows)


async def test_the_oldest_of_many_memories_is_found_by_its_words(engine: AsyncEngine) -> None:
    await the_oldest_is_found(engine)


async def test_without_full_text_search_sql_server_still_finds_the_oldest(engine: AsyncEngine) -> None:
    if engine.dialect.name != "mssql":
        pytest.skip("the fallback for a SQL Server without Full-Text Search")
    with patch.dict(memories_module._FULL_TEXT, {str(engine.url): False}):  # pyright: ignore[reportPrivateUsage]
        await the_oldest_is_found(engine)


async def the_oldest_is_found(engine: AsyncEngine) -> None:
    store = Memories(engine)
    with tenant_scope(f"m-{uuid4().hex[:8]}"):
        await keep(store, "branch", "Leeds Central opens at nine", created_at="2020-01-01T00:00:00.000Z")
        # The search needs many newer rows, not many saves: one insert, so a SQL Server run across Fly's network takes
        # seconds instead of minutes (slow-tests RCA A2). Two saves keep the save path in the walk.
        await keep(store, "note saved", "Routine branch note saved about the weekly rota")
        await seed_notes(store, 250)
        await keep(store, "note saved last", "Routine branch note saved last about the weekly rota")
        found = await eventually(lambda: store.matches("p@x", "team_ops", "ag_x", ["leeds", "branch"], limit=10))
    assert [r["value"] for r in found][:1] == ["Leeds Central opens at nine"], [r["value"] for r in found]


async def test_a_word_does_not_match_inside_another_word(engine: AsyncEngine) -> None:
    store = Memories(engine)
    with tenant_scope(f"m-{uuid4().hex[:8]}"):
        await keep(store, "travel", "Books an airplane seat by the aisle")
        await keep(store, "plan", "Sends the weekly plan on Mondays")
        found = await eventually(lambda: store.matches("p@x", "team_ops", "ag_x", ["plan"], limit=10))
    assert [r["key"] for r in found] == ["plan"], [r["key"] for r in found]


def test_a_search_word_holding_a_quote_never_reaches_sql_server_full_text_search() -> None:
    literal = memories_module._contains_literal(["leeds", "o'brien", "x'); DROP TABLE t;--", "plan"])  # pyright: ignore[reportPrivateUsage]
    assert literal == 'N\'"leeds" OR "plan"\''
