"""A local copy of another service's records, on each database, by failure mode: an event applied twice (the relay
delivers at least once), an older event arriving after a newer one, a delete, an older event arriving after a delete, a
copy row lost or left stale that only the resync repairs, a resync deleting a row an event wrote while the owner
answered, a resync holding a transaction across its call to the owner, tombstones that never go, a copy that lets one
tenant see or change another's rows, and a resync whose failing pass never shows on /health/background."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.settings import Settings
from ops_store import background, copies, isolation
from ops_store.backends import backends
from ops_store.conformance import engine_for, sql_server_database
from ops_store.copies import apply, copy_table, resync
from ops_store.database import open_database
from ops_store.outbox import Event, ToolPublished
from ops_store.schema import isolation_ddl, role_ddl, security_ddl
from ops_store.testing import loop_reports_failure

SQL_SERVER = (os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD"))
ROLE = "ops_copies_test"
# The service's system role a resync reconciles every tenant's rows as: BYPASSRLS on PostgreSQL, the chain's system
# user on SQL Server.
SYSTEM = "ops_copies_sys"
CHAIN = "copies_test"
EVERY_TENANT = "the resync reconciles every tenant's copy rows"
meta = sa.MetaData()
tools = copy_table(meta, "store_test_copy_tools", sa.Column("name", sa.String(120), nullable=False))
RESYNC_KEY = "copies_test_resync"


def published(tenant: str, tool: str, revision: int, name: str, *, deleted: bool = False) -> Event:
    return Event(
        name="tool.module.published",
        tenant_id=tenant,
        team_id="team_a",
        revision=revision,
        payload=ToolPublished(id=tool, name=name, deleted=deleted),
    )


def deleted(tenant: str, tool: str, revision: int) -> Event:
    return published(tenant, tool, revision, "Gone", deleted=True)


@pytest.fixture(params=["postgresql", "mssql"])
async def engine(request: pytest.FixtureRequest) -> AsyncIterator[AsyncEngine]:
    with sql_server_database("ops_copies", *SQL_SERVER) as mssql:
        if request.param == "mssql":
            if mssql is None:
                pytest.skip("set OPS_MSSQL_SERVER and MSSQL_SA_PASSWORD to run on SQL Server")
            url = mssql
        else:
            (backend,) = backends(Settings().database_url)
            await (await engine_for(backend)).dispose()
            url = backend.url
        e = open_database(url)
        async with e.begin() as c:
            await c.run_sync(meta.drop_all)
            await c.run_sync(meta.create_all)
            if request.param == "postgresql":
                await c.execute(
                    sa.text(
                        f"DO $$ BEGIN CREATE ROLE {ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
                    )
                )
                await c.execute(sa.text(role_ddl(SYSTEM, bypass=True)))
                statements: list[str] = []
                for table in meta.sorted_tables:
                    for role in (ROLE, SYSTEM):
                        await c.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table.name} TO {role}"))
                    statements += isolation_ddl(table, "postgresql")
            else:
                await c.execute(sa.text(f"CREATE USER {SYSTEM} WITHOUT LOGIN"))
                for table in meta.sorted_tables:
                    await c.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.{table.name} TO {SYSTEM}"))
                statements = security_ddl(
                    CHAIN, meta.sorted_tables, column_type=lambda _c: "NVARCHAR(64)", system_user=SYSTEM
                )
            for statement in statements:
                await c.execute(sa.text(statement))
        yield e
        async with e.begin() as c:
            if request.param == "mssql":
                for table in meta.sorted_tables:
                    await c.execute(sa.text(f"DROP SECURITY POLICY IF EXISTS ops_security.{table.name}_tenant"))
            await c.run_sync(meta.drop_all)
        await e.dispose()


async def deliver(engine: AsyncEngine, *events: Event) -> None:
    """Each event applied as its own tenant, on the role the policy holds, the way the receiving route applies it."""
    for ev in events:
        with isolation.scope(ev.tenant_id, ev.team_id):
            async with isolation.isolated_tx(engine, role=ROLE if _pg(engine) else None) as c:
                await apply(c, tools, ev)


async def copied(engine: AsyncEngine, tenant: str) -> dict[str, tuple[int, str]]:
    """What `tenant` sees of the copy, with no WHERE clause: only the database's policy can narrow it."""
    with isolation.scope(tenant, "team_a"):
        async with isolation.isolated_tx(engine, role=ROLE if _pg(engine) else None) as c:
            found = list(await c.execute(sa.select(tools.c.id, tools.c.revision, tools.c.name)))
    seen = {str(r.id): (int(r.revision), str(r.name)) for r in found}
    assert len(seen) == len(found), f"{tenant} sees another tenant's row: {found}"
    return seen


def _pg(engine: AsyncEngine) -> bool:
    return engine.dialect.name == "postgresql"


def as_system(engine: AsyncEngine) -> Any:
    return isolation.system_tx(engine, EVERY_TENANT, role=SYSTEM)


async def test_an_event_applies_once_and_its_redelivery_changes_nothing(engine: AsyncEngine) -> None:
    first = published("t1", "crm.find", 3, "Find a contact")
    await deliver(engine, first, first, first)
    assert await copied(engine, "t1") == {"crm.find": (3, "Find a contact")}
    await deliver(engine, published("t1", "crm.find", 4, "Find a person"))
    assert await copied(engine, "t1") == {"crm.find": (4, "Find a person")}


async def test_an_older_event_arriving_late_does_not_overwrite_a_newer_row(engine: AsyncEngine) -> None:
    await deliver(engine, published("t1", "crm.find", 7, "Find a person"))
    await deliver(engine, published("t1", "crm.find", 5, "Find a contact"), published("t1", "crm.find", 7, "Stale"))
    assert await copied(engine, "t1") == {"crm.find": (7, "Find a person")}


async def test_a_delete_event_removes_the_row_and_an_older_one_leaves_a_newer_row(engine: AsyncEngine) -> None:
    await deliver(engine, published("t1", "crm.find", 2, "Find"), published("t1", "crm.send", 6, "Send"))
    await deliver(engine, deleted("t1", "crm.find", 3), deleted("t1", "crm.send", 5))
    assert await copied(engine, "t1") == {"crm.send": (6, "Send")}


async def test_an_older_event_arriving_after_a_delete_does_not_bring_the_row_back(engine: AsyncEngine) -> None:
    await deliver(engine, published("t1", "crm.find", 2, "Find"), deleted("t1", "crm.find", 3))
    await deliver(engine, published("t1", "crm.find", 2, "Find"), published("t1", "crm.find", 3, "Find"))
    await deliver(engine, deleted("t1", "crm.early", 4), published("t1", "crm.early", 1, "Before its delete"))
    assert await copied(engine, "t1") == {}
    await deliver(engine, published("t1", "crm.find", 4, "Back"))
    assert await copied(engine, "t1") == {"crm.find": (4, "Back")}


async def test_one_tenant_neither_sees_nor_changes_another_tenants_copy_of_the_same_id(engine: AsyncEngine) -> None:
    await deliver(engine, published("t1", "crm.find", 1, "Ours"), published("t2", "crm.find", 9, "Theirs"))
    assert await copied(engine, "t1") == {"crm.find": (1, "Ours")}
    assert await copied(engine, "t2") == {"crm.find": (9, "Theirs")}
    await deliver(engine, deleted("t2", "crm.find", 10))
    assert await copied(engine, "t1") == {"crm.find": (1, "Ours")}
    assert await copied(engine, "t2") == {}


@dataclass
class Owner:
    """The owning service's full list, which a test edits and can take down. `during` runs inside the call, as an
    event the relay delivers while the owner answers; `open_txs` is how many of the pass's transactions were open."""

    records: list[Event] = field(default_factory=list[Event])
    down: bool = False
    during: Callable[[], Awaitable[None]] | None = None
    open_txs: list[int] = field(default_factory=list[int])
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    opened: int = 0

    async def list(self) -> Sequence[Event]:
        self.open_txs.append(self.opened)
        self.stop.set()
        if self.down:
            raise ConnectionError("tools-service is down")
        if self.during is not None:
            await self.during()
        return list(self.records)


async def one_pass(engine: AsyncEngine, owner: Owner, *, clock: Callable[[], float] = time.time) -> None:
    """One resync pass through `background.run_sweep`, as a service runs it, on a tx factory counting what is open."""

    @asynccontextmanager
    async def tx() -> AsyncGenerator[AsyncConnection]:
        async with as_system(engine) as c:
            owner.opened += 1
            try:
                yield c
            finally:
                owner.opened -= 1

    process = background.register(resync(tools, owner.list, key=RESYNC_KEY, service="copies_test", every_s=60.0))
    beats = background.MemoryHeartbeats()
    try:
        await background.run_sweep(RESYNC_KEY, tx, stop=owner.stop, store=beats, clock=clock)
    finally:
        background.PROCESSES.remove(process)
        del background.BY_KEY[process.key]
    (beat,) = await beats.read()
    assert beat.last_error is None, beat.last_error


async def test_resync_repairs_a_deleted_a_stale_and_an_unlisted_copy_row(engine: AsyncEngine) -> None:
    await deliver(
        engine,
        published("t1", "crm.find", 4, "Find"),
        published("t1", "crm.send", 2, "Send"),
        published("t2", "crm.gone", 1, "Gone"),
    )
    async with as_system(engine) as c:  # a row lost from the copy, as a missed event or a restore would leave it
        await c.execute(tools.delete().where(tools.c.id == "crm.find"))
    await one_pass(engine, Owner([published("t1", "crm.find", 4, "Find"), published("t1", "crm.send", 3, "Send it")]))
    assert await copied(engine, "t1") == {"crm.find": (4, "Find"), "crm.send": (3, "Send it")}
    assert await copied(engine, "t2") == {}
    await deliver(engine, published("t2", "crm.gone", 1, "Gone"))
    assert await copied(engine, "t2") == {}, "a row the resync removed came back with the event it already had"


async def test_resync_keeps_rows_an_event_wrote_while_the_owner_answered(engine: AsyncEngine) -> None:
    await deliver(engine, published("t1", "crm.find", 2, "Find"), published("t1", "crm.old", 1, "Old"))

    async def event_arrives() -> None:
        await deliver(engine, published("t1", "crm.find", 5, "Find a person"), published("t1", "crm.new", 1, "New"))

    await one_pass(engine, Owner([published("t1", "crm.send", 1, "Send")], during=event_arrives))
    assert await copied(engine, "t1") == {
        "crm.find": (5, "Find a person"),
        "crm.new": (1, "New"),
        "crm.send": (1, "Send"),
    }


async def test_resync_calls_the_owner_with_no_transaction_open(engine: AsyncEngine) -> None:
    owner = Owner([published("t1", "crm.find", 1, "Find")])
    await one_pass(engine, owner)
    assert owner.open_txs == [0], f"the owner was called with {owner.open_txs[0]} transaction(s) open"
    assert await copied(engine, "t1") == {"crm.find": (1, "Find")}


async def test_resync_prunes_only_tombstones_past_their_age_the_owner_no_longer_lists(engine: AsyncEngine) -> None:
    graves = copies.tombstones(tools)
    await deliver(engine, deleted("t1", "crm.old", 3), deleted("t1", "crm.young", 3))
    async with as_system(engine) as c:
        await c.execute(
            graves.update()
            .where(graves.c.id == "crm.old")
            .values(deleted_at=time.time() - copies.TOMBSTONE_KEEP_S - 60)
        )
    # The owner's list predates the delete of crm.young: the resync neither writes it back nor drops its tombstone.
    await one_pass(engine, Owner([published("t1", "crm.young", 2, "Young")]))
    async with as_system(engine) as c:
        left = {str(r.id) for r in await c.execute(sa.select(graves.c.id))}
    assert left == {"crm.young"}
    assert await copied(engine, "t1") == {}


class Health:
    """What `loop_reports_failure` reads: the service's /health/background answer, from its heartbeats."""

    def __init__(self, beats: background.MemoryHeartbeats, service: str) -> None:
        self.beats, self.service = beats, service

    async def get(self, url: str, /) -> Health:
        assert url == "/health/background"
        self.answer = {"processes": background.report(await self.beats.read(), self.service, time.time())}
        return self

    def json(self) -> Any:
        return self.answer


async def test_a_failing_resync_pass_shows_on_health(engine: AsyncEngine) -> None:
    owner = Owner([published("t1", "crm.find", 1, "Find")])
    process = background.register(resync(tools, owner.list, key=RESYNC_KEY, service="copies_test", every_s=0.05))
    beats, stop = background.MemoryHeartbeats(), asyncio.Event()
    loop = asyncio.create_task(background.run_sweep(process.key, lambda: as_system(engine), stop=stop, store=beats))
    try:
        await loop_reports_failure(
            Health(beats, "copies_test"), "copies_test_resync", lambda: setattr(owner, "down", True)
        )
    finally:
        stop.set()
        await loop
        background.PROCESSES.remove(process)
        del background.BY_KEY[process.key]
