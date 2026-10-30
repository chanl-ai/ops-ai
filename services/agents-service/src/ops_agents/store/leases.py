"""Per-thread leases: one run at a time per thread, across processes, and a way to tell a dead owner from a slow one.

A run takes the lease under the thread's lock: insert, or take over a row whose expiry has passed. The owner
renews it every third of the TTL while the run lasts and deletes it at the end. A lease past expiry means its owner
stopped renewing, which is a crashed process; the sweeper takes such leases over and continues the thread.

Each acquire or takeover raises the thread's generation by one, and the row outlives its run (release marks it
released instead of deleting it) so the counter never restarts. The generation is the fencing token: checkpoint and
gateway writes carry it, and a write whose generation is below the thread's current one is refused, so a stalled
owner that wakes after a takeover cannot overwrite the new owner's work.

Times are epoch seconds from the database's clock (`ops_store.dialect.db_epoch`), never a process clock, so processes
on hosts with skewed clocks agree on when a lease expires (ADR-0016).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_checkpointer import LeaseSupersededError
from ops_store import Guarantee
from ops_store.dialect import db_epoch, insert_ignore, lock_key, locked

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


def db_now(_engine: AsyncEngine) -> Any:
    """The database's current time in epoch seconds, as a SQL expression."""
    return db_epoch()


async def check_fence(conn: AsyncConnection, thread_id: str, generation: int | None) -> None:
    """Refuses a run's write when the thread's lease has moved past the run's generation. Runs inside the write's own
    transaction and locks the lease row, so a takeover cannot commit between this check and the write (ADR-0016). The
    lock is exclusive on both databases (SQL Server has no shared row lock held to the end of a transaction); a
    thread's writes are already one at a time under its lease, so nothing waits that did not before. A write with no
    generation is not a leased run's write and is not checked."""
    if generation is None:
        return
    q = sa.select(thread_leases.c.generation).where(thread_leases.c.thread_id == thread_id)
    current = (await conn.execute(locked(q, thread_leases))).scalar_one_or_none()
    if current is not None and int(current) != generation:
        raise LeaseSupersededError(f"lease superseded: write generation {generation}, current {current}")


TakeoverHook = Callable[[str, int], Awaitable[None]]


async def thread_lock(conn: AsyncConnection, thread_id: str) -> None:
    """Serialises, until the transaction ends, everything that decides what a thread is doing: taking its lease and
    delivering a message to it. Without it a lease could be taken between a delivery's look at the thread and its
    write, and the message would land as delivered on a run that never reads it."""
    await lock_key(conn, thread_id)


class Leases:
    # The takeover is conditional on the expiry under the thread's lock (CAS), expiry is read from the database's clock
    # (CLOCK), and taking a lease serialises with deliveries on that lock (LOCK).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.CLOCK, Guarantee.LOCK})

    def __init__(self, engine: AsyncEngine, owner: str, ttl: float, *, on_takeover: TakeoverHook | None = None) -> None:
        self.engine = engine
        self.owner = owner
        self.ttl = ttl
        # Called after an acquire that took over a lease its owner never released (a crash or a stall, not a finished
        # run), with the new generation, before the caller resumes the thread (E2c). It must not raise.
        self.on_takeover = on_takeover

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
        this = thread_leases.c.thread_id == thread_id
        generation, took_over = 0, False
        async with self.engine.begin() as c:
            await thread_lock(c, thread_id)
            # Each write below is conditional in one statement, so it settles a race by itself where the thread lock
            # takes none (SQLite): the insert does nothing when another made the row, the takeover changes nothing
            # when the lease is live. The row lock keeps what was read until the transaction ends.
            mine = locked(sa.select(thread_leases.c.released_at).where(this), thread_leases)
            before = (await c.execute(mine)).first()
            row = {"thread_id": thread_id, "generation": 1, **values}
            if before is None and (await c.execute(insert_ignore(c, thread_leases, row, keys=["thread_id"]))).rowcount:
                generation = 1
            elif before is not None:
                took = await c.execute(
                    thread_leases.update()
                    .where(this, thread_leases.c.expires_at < now)
                    .values(**values, generation=thread_leases.c.generation + 1)
                )
                if took.rowcount:
                    generation = int((await c.execute(sa.select(thread_leases.c.generation).where(this))).scalar_one())
                    # An unreleased row taken over was a live-looking owner's, the case the tools-service fence must
                    # hear about first.
                    took_over = before.released_at is None
            held = None if generation else (await c.execute(self._held(thread_id))).mappings().first()
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
