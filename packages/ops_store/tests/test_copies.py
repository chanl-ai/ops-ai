"""A local copy of another service's records, on each database, by failure mode: an event applied twice (the relay
delivers at least once), an older event arriving after a newer one, a delete, an older event arriving after a delete, a
copy row lost or left stale that only the resync repairs, a resync deleting a row an event wrote while the owner
answered, a resync holding a transaction across its call to the owner, tombstones that never go, a copy that lets one
tenant see or change another's rows, and a resync whose failing pass never shows on /health/background."""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.settings import Settings
from ops_store import background, copies, isolation
from ops_store.backends import backends
from ops_store.conformance import engine_for, sql_server_database
from ops_store.copies import apply, copy_table, reconcile, resync
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
    """What `tenant` sees of the copy's live rows, with no tenant clause: only the database's policy can narrow it."""
    with isolation.scope(tenant, "team_a"):
        async with isolation.isolated_tx(engine, role=ROLE if _pg(engine) else None) as c:
            found = list(
                await c.execute(sa.select(tools.c.id, tools.c.revision, tools.c.name).where(copies.live(tools)))
            )
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


class PausedAtInsert:
    """A connection that waits before its first INSERT until `other` has finished (or a second has passed, when the
    other transaction is waiting on this one's locks), so another transaction commits between two statements of one
    unit of work."""

    def __init__(self, conn: AsyncConnection, reached: asyncio.Event, other: asyncio.Event) -> None:
        self.conn, self.reached, self.other, self.paused = conn, reached, other, False

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(statement, sa.Insert) and not self.paused:
            self.paused = True
            self.reached.set()
            await asyncio.wait([asyncio.ensure_future(self.other.wait())], timeout=1.0)
        return await self.conn.execute(statement, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.conn, name)


async def interleaved(engine: AsyncEngine, paused: Callable[[AsyncConnection], Awaitable[None]], event: Event) -> None:
    """`paused` runs in its own transaction, stopping before its first INSERT; `event` is delivered and committed in a
    second transaction at that point, then `paused` resumes and commits."""
    reached, done = asyncio.Event(), asyncio.Event()

    async def first() -> None:
        with isolation.scope(event.tenant_id, event.team_id):
            try:
                async with isolation.isolated_tx(engine, role=ROLE if _pg(engine) else None) as c:
                    await paused(cast(AsyncConnection, PausedAtInsert(c, reached, done)))
            finally:
                reached.set()  # a unit of work with no INSERT still lets the other transaction run

    async def second() -> None:
        await reached.wait()
        try:
            await deliver(engine, event)
        finally:
            done.set()

    await asyncio.gather(first(), second())


async def test_an_event_and_a_delete_in_overlapping_transactions_leave_the_delete(engine: AsyncEngine) -> None:
    await interleaved(engine, lambda c: apply(c, tools, deleted("t1", "r1", 3)), published("t1", "r1", 2, "Old"))
    assert await copied(engine, "t1") == {}
    await deliver(engine, published("t1", "r1", 2, "Old"))
    assert await copied(engine, "t1") == {}


async def test_a_resync_whose_insert_meets_an_event_for_the_same_key_completes(engine: AsyncEngine) -> None:
    async def pass_writes(c: AsyncConnection) -> None:
        await reconcile(c, tools, [published("t1", "crm.find", 4, "Find")], {})

    # The pass runs as the event's tenant here, since only the overlap is under test, not the system role.
    await interleaved(engine, pass_writes, published("t1", "crm.find", 5, "Find a person"))
    assert await copied(engine, "t1") == {"crm.find": (5, "Find a person")}


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


async def test_resync_prunes_old_tombstones_and_brings_back_a_record_the_owner_lists(engine: AsyncEngine) -> None:
    await deliver(engine, deleted("t1", "crm.old", 3), deleted("t1", "crm.young", 3))
    async with as_system(engine) as c:
        await c.execute(
            tools.update().where(tools.c.id == "crm.old").values(deleted_at=time.time() - copies.TOMBSTONE_KEEP_S - 60)
        )
    # The owner lists crm.young below its delete: the list is the truth, so the record is back.
    await one_pass(engine, Owner([published("t1", "crm.young", 2, "Young")]))
    async with as_system(engine) as c:
        left = {str(r.id) for r in await c.execute(sa.select(tools.c.id))}
    assert left == {"crm.young"}
    assert await copied(engine, "t1") == {"crm.young": (2, "Young")}


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


async def test_resync_sets_the_copy_to_the_owners_list_at_any_revision(engine: AsyncEngine) -> None:
    await deliver(engine, published("t1", "crm.find", 4, "Find"), deleted("t1", "crm.send", 7))
    # An edit at the same revision, and a record re-created after the owner's counter restarted.
    await one_pass(
        engine, Owner([published("t1", "crm.find", 4, "Find a contact"), published("t1", "crm.send", 1, "Send")])
    )
    assert await copied(engine, "t1") == {"crm.find": (4, "Find a contact"), "crm.send": (1, "Send")}
    await deliver(engine, published("t1", "crm.send", 2, "Send it"))
    assert await copied(engine, "t1") == {"crm.find": (4, "Find a contact"), "crm.send": (2, "Send it")}


async def test_events_deletes_recreates_and_passes_in_any_order_converge_on_one_last_pass(engine: AsyncEngine) -> None:
    rng = random.Random(20261115)
    keys = [f"crm.k{i}" for i in range(4)]
    owner: dict[str, Event] = {}
    counter = dict.fromkeys(keys, 0)
    sent: list[Event] = []
    for step in range(300):
        roll, key = rng.random(), rng.choice(keys)
        if roll < 0.45:
            if key in owner and rng.random() < 0.25:
                counter[key] += 1
                del owner[key]
                sent.append(deleted("t1", key, counter[key]))
            else:
                if rng.random() < 0.1:
                    counter[key] = 0  # the owner's counter restarts
                counter[key] += rng.choice([0, 1, 1, 2])  # 0: an edit at the same revision
                owner[key] = published("t1", key, counter[key], f"v{step}")
                sent.append(owner[key])
        elif roll < 0.85 and sent:
            event = rng.choice(sent)  # delivered late, out of order, and some more than once
            if rng.random() < 0.7:
                sent.remove(event)
            await deliver(engine, event)
        else:
            await one_pass(engine, Owner(list(owner.values())))
    await one_pass(engine, Owner(list(owner.values())))
    want = {k: (e.revision, e.payload.model_dump()["name"]) for k, e in owner.items()}
    assert await copied(engine, "t1") == want
