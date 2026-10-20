"""Each suite passes on an implementation that keeps its guarantee and fails on one that does not; a suite that
cannot fail would certify anything. The lease and timer implementations here are test references on PostgreSQL; the
services run the same suites on their own repositories."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.settings import Settings
from ops_store import Backend, Guarantee
from ops_store.backends import backends
from ops_store.conformance import audit_suite, engine_for, lease_suite, timer_claim_suite
from ops_store.reference import SqlAuditLog

meta = sa.MetaData()
leases = sa.Table(
    "store_test_leases",
    meta,
    sa.Column("key", sa.String(64), primary_key=True),
    sa.Column("holder", sa.String(64), nullable=False),
    sa.Column("generation", sa.Integer, nullable=False),
    sa.Column("expires_at", sa.Float(asdecimal=False), nullable=False),
)
timers = sa.Table(
    "store_test_timers",
    meta,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("generation", sa.Integer, nullable=False),
    sa.Column("claimed", sa.Boolean, nullable=False),
)
NOW = sa.func.extract("epoch", sa.func.clock_timestamp())


class Leases:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.CLOCK})
    ttl = 0.4

    def __init__(self, engine: AsyncEngine, *, cas: bool = True) -> None:
        self.engine, self.cas = engine, cas

    async def try_acquire(self, key: str, holder: str) -> int | None:
        async with self.engine.begin() as c:
            ins = insert(leases).values(key=key, holder=holder, generation=1, expires_at=NOW + self.ttl)
            took = ins.on_conflict_do_update(
                index_elements=[leases.c.key],
                set_={"holder": holder, "generation": leases.c.generation + 1, "expires_at": NOW + self.ttl},
                where=leases.c.expires_at < NOW if self.cas else sa.true(),
            ).returning(leases.c.generation)
            return (await c.execute(took)).scalar()

    async def write_fenced(self, key: str, generation: int) -> bool:
        async with self.engine.begin() as c:
            q = (
                leases.update()
                .where(leases.c.key == key, leases.c.generation == generation)
                .values(holder=leases.c.holder)
            )
            return (await c.execute(q)).rowcount == 1


class Timers:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine, *, cas: bool = True) -> None:
        self.engine, self.cas = engine, cas

    async def arm(self, timer_id: str, generation: int) -> None:
        async with self.engine.begin() as c:
            await c.execute(timers.insert().values(id=timer_id, generation=generation, claimed=False))

    async def claim(self, timer_id: str, generation: int) -> bool:
        async with self.engine.begin() as c:
            if not self.cas:
                row = (await c.execute(sa.select(timers.c.claimed).where(timers.c.id == timer_id))).scalar()
                await c.execute(timers.update().where(timers.c.id == timer_id).values(claimed=True))
                return row is False
            q = timers.update().where(timers.c.id == timer_id, timers.c.generation == generation, ~timers.c.claimed)
            return (await c.execute(q.values(claimed=True))).rowcount == 1


class NoTransactionAudit(SqlAuditLog):
    """Writes the change and the entry separately: the change lands even when the entry is refused."""

    async def apply(self, entity_id: str, value: str, entry: dict[str, Any] | None) -> None:
        from ops_store.reference import audit_entries, audited  # noqa: PLC0415

        async with self.engine.begin() as c:
            if (await c.execute(audited.update().where(audited.c.id == entity_id).values(value=value))).rowcount == 0:
                await c.execute(audited.insert().values(id=entity_id, value=value))
        async with self.engine.begin() as c:
            await c.execute(audit_entries.insert().values(entity_id=entity_id, entry=entry))


@pytest.fixture(params=backends(Settings().database_url), ids=lambda b: b.name)
async def backend(request: pytest.FixtureRequest) -> AsyncIterator[tuple[Backend, AsyncEngine]]:
    b: Backend = request.param
    engine = await engine_for(b)
    async with engine.begin() as c:
        await c.run_sync(meta.create_all)
    yield b, engine
    await engine.dispose()


async def test_leases_conform_and_a_lease_without_cas_does_not(backend: tuple[Backend, AsyncEngine]) -> None:
    b, engine = backend
    await lease_suite(b, lambda: _ready(Leases(engine)))
    with pytest.raises(AssertionError, match="refuses a second holder"):
        await lease_suite(b, lambda: _ready(Leases(engine, cas=False)))


async def test_timer_claims_conform_and_a_read_then_write_claim_does_not(backend: tuple[Backend, AsyncEngine]) -> None:
    b, engine = backend
    await timer_claim_suite(b, lambda: _ready(Timers(engine)))
    with pytest.raises(AssertionError, match="pollers claimed one timer"):
        await timer_claim_suite(b, lambda: _ready(Timers(engine, cas=False)))


async def test_audit_conforms_and_a_split_write_does_not(backend: tuple[Backend, AsyncEngine]) -> None:
    b, engine = backend
    await audit_suite(b, lambda: SqlAuditLog(engine).create())
    with pytest.raises(AssertionError, match="neither the change nor an entry landed"):
        await audit_suite(b, lambda: NoTransactionAudit(engine).create())


async def test_a_backend_missing_a_guarantee_is_refused(backend: tuple[Backend, AsyncEngine]) -> None:
    _, engine = backend
    no_clock = Backend("no-clock", "", frozenset({Guarantee.CAS}))
    with pytest.raises(AssertionError, match="needs \\['clock'\\]"):
        await lease_suite(no_clock, lambda: _ready(Leases(engine)))


async def _ready[T](x: T) -> T:
    return x


def test_two_test_databases_get_two_conformance_databases_on_the_same_server() -> None:
    (a,) = backends("postgresql+asyncpg://ops:ops@localhost:5477/ops_test_a")
    (b,) = backends("postgresql+asyncpg://ops:ops@localhost:5477/ops_test_b")
    ua, ub = make_url(a.url), make_url(b.url)
    assert (ua.database, ub.database) == ("ops_test_a_conformance", "ops_test_b_conformance")
    assert (ua.host, ua.port, ua.password) == (ub.host, ub.port, ub.password) == ("localhost", 5477, "ops")
