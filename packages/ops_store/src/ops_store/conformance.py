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
import time
from collections.abc import Awaitable, Callable
from secrets import token_hex

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .guarantees import Backend, unmet
from .ports import AuditPort, LeasePort, TimerClaimPort

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
