"""A local copy of another service's records, on each database, by failure mode: an event applied twice (the relay
delivers at least once), an older event arriving after a newer one, a delete, a copy row lost or left stale that only
the resync repairs, a copy that lets one tenant see or change another's rows, and a resync whose failing pass never
shows on /health/background."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.settings import Settings
from ops_store import background, isolation
from ops_store.backends import backends
from ops_store.conformance import engine_for, sql_server_database
from ops_store.copies import apply, copy_table, resync
from ops_store.database import open_database
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
tools = copy_table(
    meta,
    "store_test_copy_tools",
    sa.Column("name", sa.String(120), nullable=False),
    sa.Column("app", sa.String(64), nullable=False),
)


@dataclass(frozen=True)
class Ev:
    tenant_id: str
    revision: int
    payload: dict[str, Any]
    team_id: str | None = "team_a"
    name: str = "tool.module.changed"


def published(tenant: str, tool: str, revision: int, name: str, **more: Any) -> Ev:
    return Ev(tenant, revision, {"id": tool, "name": name, "app": "crm", **more})


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
                for role in (ROLE, SYSTEM):
                    await c.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tools.name} TO {role}"))
                statements = isolation_ddl(tools, "postgresql")
            else:
                await c.execute(sa.text(f"CREATE USER {SYSTEM} WITHOUT LOGIN"))
                await c.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.{tools.name} TO {SYSTEM}"))
                statements = security_ddl(CHAIN, [tools], column_type=lambda _c: "NVARCHAR(64)", system_user=SYSTEM)
            for statement in statements:
                await c.execute(sa.text(statement))
        yield e
        async with e.begin() as c:
            if request.param == "mssql":
                await c.execute(sa.text(f"DROP SECURITY POLICY IF EXISTS ops_security.{tools.name}_tenant"))
            await c.run_sync(meta.drop_all)
        await e.dispose()


async def deliver(engine: AsyncEngine, *events: Ev) -> None:
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
    await deliver(
        engine, Ev("t1", 3, {"id": "crm.find", "deleted": True}), Ev("t1", 5, {"id": "crm.send", "deleted": True})
    )
    assert await copied(engine, "t1") == {"crm.send": (6, "Send")}


async def test_one_tenant_neither_sees_nor_changes_another_tenants_copy_of_the_same_id(engine: AsyncEngine) -> None:
    await deliver(engine, published("t1", "crm.find", 1, "Ours"), published("t2", "crm.find", 9, "Theirs"))
    assert await copied(engine, "t1") == {"crm.find": (1, "Ours")}
    assert await copied(engine, "t2") == {"crm.find": (9, "Theirs")}
    await deliver(engine, Ev("t2", 10, {"id": "crm.find", "deleted": True}))
    assert await copied(engine, "t1") == {"crm.find": (1, "Ours")}
    assert await copied(engine, "t2") == {}


@dataclass
class Owner:
    """The owning service's full list, which a test edits and can take down."""

    records: list[Ev] = field(default_factory=list[Ev])
    down: bool = False

    async def list(self) -> Sequence[Ev]:
        if self.down:
            raise ConnectionError("tools-service is down")
        return list(self.records)


async def test_resync_repairs_a_deleted_a_stale_and_an_unlisted_copy_row(engine: AsyncEngine) -> None:
    await deliver(
        engine,
        published("t1", "crm.find", 4, "Find"),
        published("t1", "crm.send", 2, "Send"),
        published("t2", "crm.gone", 1, "Gone"),
    )
    async with as_system(engine) as c:  # a row lost from the copy, as a missed event or a restore would leave it
        await c.execute(tools.delete().where(tools.c.id == "crm.find"))
    owner = Owner([published("t1", "crm.find", 4, "Find"), published("t1", "crm.send", 3, "Send it")])
    process = resync(tools, owner.list, key="copies_test_resync", service="copies_test", every_s=60.0)
    assert process.sweep is not None
    async with as_system(engine) as c:  # a service passes its own system_tx with its reason and role
        await process.sweep(c, time.time())
    assert await copied(engine, "t1") == {"crm.find": (4, "Find"), "crm.send": (3, "Send it")}
    assert await copied(engine, "t2") == {}


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
    process = background.register(
        resync(tools, owner.list, key="copies_test_resync", service="copies_test", every_s=0.05)
    )
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
