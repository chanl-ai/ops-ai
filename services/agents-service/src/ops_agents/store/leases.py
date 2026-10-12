"""Per-thread leases: one run at a time per thread, across processes, and a way to tell a dead owner from a slow one.

A run takes the lease with one conditional upsert: insert, or take over a row whose expiry has passed. The owner
renews it every third of the TTL while the run lasts and deletes it at the end. A lease past expiry means its owner
stopped renewing, which is a crashed process; the sweeper takes such leases over and continues the thread.

Each acquire or takeover raises the thread's generation by one, and the row outlives its run (release marks it
released instead of deleting it) so the counter never restarts. The generation is the fencing token: checkpoint and
gateway writes carry it, and a write whose generation is below the thread's current one is refused, so a stalled
owner that wakes after a takeover cannot overwrite the new owner's work.

Times are epoch seconds from the database's clock (`now()`), never a process clock, so processes on hosts with skewed
clocks agree on when a lease expires (ADR-0016).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_checkpointer import LeaseSupersededError
from ops_store import Guarantee

from .base import metadata

thread_leases = sa.Table(
    "thread_leases",
    metadata,
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("owner", sa.String(120), nullable=False),
    sa.Column("run_id", sa.String(64), nullable=False),
    sa.Column("acquired_at", sa.Float(), nullable=False),
    sa.Column("heartbeat_at", sa.Float(), nullable=False),
    sa.Column("expires_at", sa.Float(), nullable=False, index=True),
    sa.Column("generation", sa.BigInteger(), nullable=False, server_default="1"),
    # Set when the owner finished and let go; an unreleased row past expiry is a crashed owner.
    sa.Column("released_at", sa.Float()),
)


@dataclass(frozen=True)
class LeaseInfo:
    thread_id: str
    owner: str
    run_id: str
    acquired_at: float
    heartbeat_at: float
    expires_at: float
    generation: int
    released_at: float | None
    # Seconds since it was taken, by the database's clock.
    age: float = 0.0


class LeaseHeldError(Exception):
    def __init__(self, held: LeaseInfo) -> None:
        super().__init__(f"Thread {held.thread_id} is leased by {held.owner}")
        self.held = held


def db_now(engine: AsyncEngine) -> Any:
    """The database's current time in epoch seconds, as a SQL expression."""
    if engine.dialect.name == "postgresql":
        return sa.func.extract("epoch", sa.func.now())
    return (sa.func.julianday("now") - 2440587.5) * 86400.0  # SQLite, for the unit tests


async def check_fence(conn: AsyncConnection, thread_id: str, generation: int | None) -> None:
    """Refuses a run's write when the thread's lease has moved past the run's generation. Runs inside the write's own
    transaction and locks the lease row FOR SHARE, so a takeover cannot commit between this check and the write
    (ADR-0016). A write with no generation is not a leased run's write and is not checked."""
    if generation is None:
        return
    q = sa.select(thread_leases.c.generation).where(thread_leases.c.thread_id == thread_id)
    if conn.dialect.name == "postgresql":
        q = q.with_for_update(read=True)
    current = (await conn.execute(q)).scalar_one_or_none()
    if current is not None and int(current) != generation:
        raise LeaseSupersededError(f"lease superseded: write generation {generation}, current {current}")


TakeoverHook = Callable[[str, int], Awaitable[None]]


async def thread_lock(conn: AsyncConnection, thread_id: str) -> None:
    """Serialises, until the transaction ends, everything that decides what a thread is doing: taking its lease and
    delivering a message to it. Without it a lease could be taken between a delivery's look at the thread and its
    write, and the message would land as delivered on a run that never reads it. PostgreSQL only; SQLite has one
    writer at a time anyway."""
    if conn.dialect.name == "postgresql":
        await conn.execute(sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:t, 0))"), {"t": thread_id})


class Leases:
    # The takeover is a conditional upsert on the expiry (CAS), expiry is read from the database's clock (CLOCK), and
    # taking a lease serialises with deliveries on the thread's advisory lock (LOCK).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.CLOCK, Guarantee.LOCK})

    def __init__(self, engine: AsyncEngine, owner: str, ttl: float, *, on_takeover: TakeoverHook | None = None) -> None:
        self.engine = engine
        self.owner = owner
        self.ttl = ttl
        # Called after an acquire that took over a lease its owner never released (a crash or a stall, not a finished
        # run), with the new generation, before the caller resumes the thread (E2c). It must not raise.
        self.on_takeover = on_takeover

    def _insert(self) -> Any:
        return (postgresql.insert if self.engine.dialect.name == "postgresql" else sqlite.insert)(thread_leases)

    def _held(self, thread_id: str) -> Any:
        age = (db_now(self.engine) - thread_leases.c.acquired_at).label("age")
        return sa.select(thread_leases, age).where(thread_leases.c.thread_id == thread_id)

    async def acquire(self, thread_id: str, run_id: str) -> int:
        """Takes the lease and returns its generation, or raises LeaseHeldError with the live holder. Taking over an
        expired or released lease is how a dead owner's lease is reclaimed; either way the generation goes up."""
        now = db_now(self.engine)
        values: dict[str, Any] = {
            "owner": self.owner,
            "run_id": run_id,
            "acquired_at": now,
            "heartbeat_at": now,
            "expires_at": now + self.ttl,
            "released_at": None,
        }
        stmt = (
            self._insert()
            .values(thread_id=thread_id, generation=1, **values)
            .on_conflict_do_update(
                index_elements=["thread_id"],
                set_={**values, "generation": thread_leases.c.generation + 1},
                where=thread_leases.c.expires_at < now,
            )
            .returning(thread_leases.c.run_id, thread_leases.c.generation)
        )
        held: Any = None
        async with self.engine.begin() as c:
            await thread_lock(c, thread_id)
            # Read under the row lock in the same transaction: an unreleased row the upsert then replaces was taken
            # over from a live-looking owner, which is the case the tools-service fence must hear about first.
            before = (
                await c.execute(
                    sa.select(thread_leases.c.released_at)
                    .where(thread_leases.c.thread_id == thread_id)
                    .with_for_update()
                )
            ).first()
            won = (await c.execute(stmt)).first()
            took_over = won is not None and before is not None and before.released_at is None
            if won is not None and won.run_id == run_id:
                generation = int(won.generation)
            else:
                generation = 0
                held = (await c.execute(self._held(thread_id))).mappings().first()
        if generation:
            if took_over and self.on_takeover is not None:
                await self.on_takeover(thread_id, generation)
            return generation
        if held is None:  # Removed between the two statements; one retry settles it.
            return await self.acquire(thread_id, run_id)
        raise LeaseHeldError(LeaseInfo(**dict(held)))

    async def heartbeat(self, thread_id: str, run_id: str) -> bool:
        """Renews the lease; False when another owner has taken it (this run must stop writing)."""
        now = db_now(self.engine)
        async with self.engine.begin() as c:
            res = await c.execute(
                thread_leases.update()
                .where(thread_leases.c.thread_id == thread_id, thread_leases.c.run_id == run_id)
                .values(heartbeat_at=now, expires_at=now + self.ttl)
            )
            return res.rowcount == 1

    async def release(self, thread_id: str, run_id: str) -> None:
        """Lets go of the lease but keeps the row, so the next acquire continues the generation count."""
        async with self.engine.begin() as c:
            await c.execute(
                thread_leases.update()
                .where(thread_leases.c.thread_id == thread_id, thread_leases.c.run_id == run_id)
                .values(released_at=db_now(self.engine), expires_at=0.0)
            )

    async def expired(self) -> list[LeaseInfo]:
        """Leases whose owner stopped renewing without releasing: crashed runs for the sweeper."""
        age = (db_now(self.engine) - thread_leases.c.acquired_at).label("age")
        q = sa.select(thread_leases, age).where(
            thread_leases.c.expires_at < db_now(self.engine), thread_leases.c.released_at.is_(None)
        )
        async with self.engine.connect() as c:
            return [LeaseInfo(**dict(r)) for r in (await c.execute(q)).mappings()]

    async def held(self, thread_id: str) -> LeaseInfo | None:
        """The unreleased lease on a thread, live or crashed; None when nobody holds it."""
        q = self._held(thread_id).where(thread_leases.c.released_at.is_(None))
        async with self.engine.connect() as c:
            row = (await c.execute(q)).mappings().first()
        return LeaseInfo(**dict(row)) if row else None

    async def generation_of(self, thread_id: str, run_id: str) -> int | None:
        """The generation this run holds, or None if it does not hold the thread's lease."""
        q = sa.select(thread_leases.c.generation).where(
            thread_leases.c.thread_id == thread_id, thread_leases.c.run_id == run_id
        )
        async with self.engine.connect() as c:
            row = (await c.execute(q)).first()
        return int(row.generation) if row else None


class Heartbeat:
    """Renews a lease in the background while a run executes; `lost` is set if another owner took it over."""

    def __init__(self, leases: Leases, thread_id: str, run_id: str) -> None:
        self._leases, self._thread_id, self._run_id = leases, thread_id, run_id
        self.lost = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._leases.ttl / 3)
            if not await self._leases.heartbeat(self._thread_id, self._run_id):
                self.lost.set()
                return

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
