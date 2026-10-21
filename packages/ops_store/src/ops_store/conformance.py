"""Conformance suites, one per port, run by each service against its own repositories on every registered backend.

Each suite takes a factory that builds a fresh repository on a backend (`backends.backends`), checks the
repository's declared guarantees are ones the backend provides, and then drives the behaviour the guarantee exists
for. A suite that passes on a repository whose guarantee is broken would be worthless, so each check is the failure
the guarantee prevents: two owners writing, a timer firing twice, a change without its audit entry.

  @pytest.mark.parametrize("backend", backends(settings.database_url), ids=lambda b: b.name)
  async def test_leases_conform(backend: Backend) -> None:
      await lease_suite(backend, lambda: MyLeases(...))
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from secrets import token_hex
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .guarantees import Backend, unmet
from .isolation import isolated_tx, scope, tenant_wide
from .ports import AuditPort, LeasePort, TimerClaimPort
from .schema import isolation_kind, team_column, tenant_column

CONTENDERS = 8


async def engine_for(backend: Backend) -> AsyncEngine:
    """An engine on the backend's conformance database, created when it does not exist yet."""
    url = make_url(backend.url)
    if url.get_backend_name() == "postgresql":
        admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        async with admin.connect() as c:
            exists = (
                await c.execute(text("select 1 from pg_database where datname = :n"), {"n": url.database})
            ).first()
            if exists is None:
                await c.execute(text(f'create database "{url.database}"'))
        await admin.dispose()
    return create_async_engine(url)


def _guarantees(repo: object, backend: Backend) -> None:
    missing = unmet(repo, backend)  # pyright: ignore[reportArgumentType]
    names = sorted(g.value for g in missing)
    assert not missing, f"{type(repo).__name__} needs {names}, which {backend.name} does not provide"


async def _until[T](attempt: Callable[[], Awaitable[T | None]], timeout: float = 10.0) -> T:
    deadline = time.monotonic() + timeout
    while (result := await attempt()) is None:
        assert time.monotonic() < deadline, "the condition did not hold in time"
        await asyncio.sleep(0.05)
    return result


async def lease_suite(backend: Backend, make: Callable[[], Awaitable[LeasePort]]) -> None:
    """Build the leases with a short `ttl` (well under a second): the suite waits it out twice."""
    a, b = await make(), await make()
    _guarantees(a, backend)
    key = f"lease-{token_hex(4)}"
    first = await a.try_acquire(key, "a")
    assert first is not None, "a free key is acquired"
    assert await b.try_acquire(key, "b") is None, "a live lease refuses a second holder"
    assert await a.write_fenced(key, first), "the owner's fenced write lands"

    second = await _until(lambda: b.try_acquire(key, "b"))
    assert second > first, "a new owner gets a newer generation"
    assert not await a.write_fenced(key, first), "the old owner's write is refused once a newer generation owns the key"
    assert await b.write_fenced(key, second)

    racers = [await make() for _ in range(CONTENDERS)]
    fresh = f"lease-{token_hex(4)}"
    won = [g for g in await asyncio.gather(*(r.try_acquire(fresh, f"r{i}") for i, r in enumerate(racers))) if g]
    assert len(won) == 1, f"{len(won)} contenders took one free key"
    await asyncio.sleep(a.ttl * 1.5)
    won = [g for g in await asyncio.gather(*(r.try_acquire(fresh, f"s{i}") for i, r in enumerate(racers))) if g]
    assert len(won) == 1, f"{len(won)} contenders took one lapsed lease"


async def timer_claim_suite(backend: Backend, make: Callable[[], Awaitable[TimerClaimPort]]) -> None:
    pollers = [await make() for _ in range(CONTENDERS)]
    _guarantees(pollers[0], backend)
    timer = f"timer-{token_hex(4)}"
    await pollers[0].arm(timer, 1)
    claims = await asyncio.gather(*(p.claim(timer, 1) for p in pollers))
    assert sum(claims) == 1, f"{sum(claims)} pollers claimed one timer"
    assert not await pollers[0].claim(timer, 1), "a claimed timer is not claimed again"


async def audit_suite(backend: Backend, make: Callable[[], Awaitable[AuditPort]]) -> None:
    log = await make()
    _guarantees(log, backend)
    entity = f"entity-{token_hex(4)}"
    await log.apply(entity, "v1", {"by": "a", "change": "set v1"})
    assert (await log.value(entity), await log.entries(entity)) == ("v1", 1), "a change lands with its entry"
    try:
        await log.apply(entity, "v2", None)
    except Exception:
        pass
    else:
        raise AssertionError("a change whose entry the store refuses must fail")
    assert (await log.value(entity), await log.entries(entity)) == ("v1", 1), "neither the change nor an entry landed"


# Isolation (c-410) -------------------------------------------------------------------------------------------------

RowFill = Callable[[str, str | None], dict[str, Any]]
# The reason the suite reads a tenant-wide view of what it wrote.
SUITE = "isolation_suite"


async def isolation_suite(
    engine: AsyncEngine, tables: Sequence[sa.Table], *, role: str, fill: Mapping[str, RowFill] | None = None
) -> list[str]:
    """Every way the database lets a transaction see or change rows its context should not, one line per failure, each
    starting with the table's name; empty when every team-owned and tenant table holds. Rows are written past
    row-level security (as the engine's own user, which must bypass it: a superuser or a BYPASSRLS role) and read back
    as `role`
    with raw SQL and no WHERE clause, so only the policy can filter: for a team table (T1, A), (T1, B), (T1, no team
    where the column allows it) and (T2, A); for a tenant table one row of each tenant. `fill` builds a row's other
    columns a table's types cannot give (a foreign key), over the values the suite makes from its types."""
    t1, t2, a, b = (f"{p}_{secrets.token_hex(3)}" for p in ("iso_t1", "iso_t2", "iso_a", "iso_b"))
    failures: list[str] = []
    for table in tables:
        kind = isolation_kind(table)
        if kind not in ("team", "tenant"):
            continue
        make = _with(_filler(table), (fill or {}).get(table.name))
        tenant = tenant_column(table)
        team = team_column(table) if kind == "team" else None
        shared = team is not None and team.nullable
        rows = (
            [(t1, a), (t1, b), (t2, a)] + ([(t1, None)] if shared else [])
            if team is not None
            else [(t1, None), (t2, None)]
        )
        async with engine.begin() as c:
            for row_tenant, row_team in rows:
                values = {**make(row_tenant, row_team), tenant.name: row_tenant}
                if team is not None:
                    values[team.name] = row_team
                await c.execute(table.insert().values(values))
        try:
            failures += [
                f"{table.name}: {f}"
                for f in await _isolation_checks(engine, table, role=role, ids=(t1, t2, a, b), make=make)
            ]
        finally:
            async with engine.begin() as c:
                await c.execute(table.delete().where(tenant.in_([t1, t2])))
    return failures


async def _isolation_checks(
    engine: AsyncEngine, table: sa.Table, *, role: str, ids: tuple[str, str, str, str], make: RowFill
) -> list[str]:
    """`ids` are the suite's two tenants and two teams."""
    t1, t2, a, b = ids
    out: list[str] = []
    tenant = tenant_column(table)
    team = team_column(table) if isolation_kind(table) == "team" else None

    async def seen() -> list[tuple[str, str | None]]:
        async with isolated_tx(engine, role=role) as c:
            cols = [tenant] + ([team] if team is not None else [])
            got = (await c.execute(sa.select(*cols).select_from(table))).all()
        return _pairs(got, team is not None)

    async def refused(values: dict[str, Any]) -> bool:
        try:
            async with isolated_tx(engine, role=role) as c:
                await c.execute(table.insert().values(values))
        except DBAPIError:
            return True
        return False

    async def changed(where: sa.ColumnElement[bool]) -> int:
        async with isolated_tx(engine, role=role) as c:
            return (await c.execute(table.update().where(where).values({tenant.name: tenant}))).rowcount

    mine = [r for r in await _all(engine, table, tenant, team) if r[0] == t1]
    if team is None:
        with scope(t1, None):
            if (got := await seen()) != mine:
                out.append(f"a tenant transaction read {got}, expected its tenant's {mine}")
            # A tenant with no rows yet, so a table keyed by tenant alone refuses only by the policy, not the key.
            t3 = f"iso_t3_{secrets.token_hex(3)}"
            if not await refused({**make(t3, None), tenant.name: t3}):
                out.append("a tenant transaction wrote another tenant's row")
            if n := await changed(tenant == t2):
                out.append(f"a tenant transaction updated {n} of another tenant's rows")
        return out
    with scope(t1, a):
        want = [r for r in mine if r[1] in (a, None)]
        if (got := await seen()) != want:
            out.append(f"team {a} read {got}, expected its rows and the null-team rows {want}")
        if not await refused({**make(t1, b), tenant.name: t1, team.name: b}):
            out.append("a team transaction wrote another team's row")
        if team.nullable and not await refused({**make(t1, None), tenant.name: t1, team.name: None}):
            out.append("a team transaction wrote a null-team row")
        if n := await changed(team == b):
            out.append(f"a team transaction updated {n} of another team's rows")
    with tenant_wide(SUITE, tenant_id=t1):
        if (got := await seen()) != mine:
            out.append(f"a tenant-wide transaction read {got}, expected every team of its tenant {mine}")
    return out


async def _all(
    engine: AsyncEngine, table: sa.Table, tenant: sa.Column[Any], team: sa.Column[Any] | None
) -> list[tuple[str, str | None]]:
    async with engine.connect() as c:
        cols = [tenant] + ([team] if team is not None else [])
        got = (await c.execute(sa.select(*cols).select_from(table))).all()
    return _pairs(got, team is not None)


def _pairs(rows: Sequence[sa.Row[Any]], has_team: bool) -> list[tuple[str, str | None]]:
    """(tenant, team) per row, sorted; team None for a tenant table and for a null-team row."""
    out: list[tuple[str, str | None]] = []
    for row in rows:
        values = tuple(row)
        out.append((str(values[0]), str(values[1]) if has_team and values[1] is not None else None))
    return sorted(out, key=lambda pair: (pair[0], pair[1] or ""))


def _with(base: RowFill, extra: RowFill | None) -> RowFill:
    """`base`'s values with `extra`'s on top: a table's own fill names only what the types cannot (a foreign key)."""
    if extra is None:
        return base
    return lambda tenant, team: {**base(tenant, team), **extra(tenant, team)}


def _filler(table: sa.Table) -> RowFill:
    """Values for every column a row needs that has no default, by type; keys get a fresh value each row."""

    def fill(_tenant: str, _team: str | None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for col in table.columns:
            needed = not col.nullable and col.default is None and col.server_default is None
            if not (col.primary_key or needed) or (col.primary_key and col.autoincrement is True):
                continue
            out[col.name] = _value(col)
        return out

    return fill


def _value(col: sa.Column[Any]) -> Any:
    kind = col.type
    if isinstance(kind, sa.Enum) and kind.enums:
        return kind.enums[0]
    if isinstance(kind, sa.String):
        return secrets.token_hex(8)[: kind.length or 16]
    if isinstance(kind, sa.Integer):
        return secrets.randbelow(2**31)
    if isinstance(kind, (sa.Float, sa.Numeric)):
        return 0
    if isinstance(kind, sa.Boolean):
        return False
    if isinstance(kind, sa.JSON):
        return {}
    if isinstance(kind, sa.DateTime):
        return datetime.now(UTC)
    if isinstance(kind, sa.Date):
        return datetime.now(UTC).date()
    if isinstance(kind, sa.LargeBinary):
        return b""
    raise ValueError(f"isolation_suite: no value for {col.table.name}.{col.name} ({kind}); pass fill=")
