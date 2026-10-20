"""agents-service's repositories on ops_store's conformance suites, on every registered backend."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.store.leases import LeaseHeldError, Leases, check_fence, thread_leases
from ops_agents.store.timers import TimerStore, timers
from ops_checkpointer import LeaseSupersededError
from ops_service_kit.settings import Settings
from ops_store import Backend, Guarantee
from ops_store.backends import backends
from ops_store.conformance import engine_for, lease_suite, timer_claim_suite


class LeasePortAdapter:
    """Leases as ops_store's LeasePort: one Leases per holder, as each process has its own owner name."""

    requires: ClassVar[frozenset[Guarantee]] = Leases.requires
    ttl = 0.5

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def try_acquire(self, key: str, holder: str) -> int | None:
        try:
            return await Leases(self.engine, owner=holder, ttl=self.ttl).acquire(key, f"run-{holder}")
        except LeaseHeldError:
            return None

    async def write_fenced(self, key: str, generation: int) -> bool:
        async with self.engine.begin() as c:
            try:
                await check_fence(c, key, generation)
            except LeaseSupersededError:
                return False
        return True


class TimerClaimAdapter:
    """TimerStore as ops_store's TimerClaimPort: each port timer is a breach timer due now on its own thread."""

    requires: ClassVar[frozenset[Guarantee]] = TimerStore.requires

    def __init__(self, engine: AsyncEngine) -> None:
        self.store = TimerStore(engine)

    async def arm(self, timer_id: str, generation: int) -> None:
        await self.store.sync(timer_id, {("t", "breach"): ("human", None, 0.0)}, None)

    async def claim(self, timer_id: str, generation: int) -> bool:
        return (await self.store.claim(timer_id, "t:breach:0", generation, waiting=True)).outcome == "claimed"


@pytest.fixture(params=backends(Settings().database_url), ids=lambda b: b.name)
async def backend(request: pytest.FixtureRequest) -> AsyncIterator[tuple[Backend, AsyncEngine]]:
    b: Backend = request.param
    engine = await engine_for(b)
    async with engine.begin() as c:
        await c.run_sync(lambda sync: thread_leases.create(sync, checkfirst=True))
        await c.run_sync(lambda sync: timers.create(sync, checkfirst=True))
    yield b, engine
    await engine.dispose()


async def test_leases_conform(backend: tuple[Backend, AsyncEngine]) -> None:
    b, engine = backend

    async def make() -> LeasePortAdapter:
        return LeasePortAdapter(engine)

    await lease_suite(b, make)


async def test_timer_claims_conform(backend: tuple[Backend, AsyncEngine]) -> None:
    b, engine = backend

    async def make() -> TimerClaimAdapter:
        return TimerClaimAdapter(engine)

    await timer_claim_suite(b, make)
