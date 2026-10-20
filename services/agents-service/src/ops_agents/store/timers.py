"""The timers table and every query on it (ADR-0016). `api/timers.py` decides what to arm, cancel and fire; this
module is how those decisions reach the database, each in one transaction.

Timers need PostgreSQL: due times are `now()` on the database's clock, and a poller skips rows another poller holds
(`SKIP LOCKED`). On SQLite, as in the unit tests, `enabled` is False and there are no timers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store import Guarantee
from ops_store.dialect import db_now

from .leases import check_fence

timers = sa.Table(
    "timers",
    sa.MetaData(),
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("timer_id", sa.String(200), primary_key=True),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("node", sa.String(64), nullable=False),
    sa.Column("interrupt_id", sa.String(64)),
    sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("fired_at", sa.DateTime(timezone=True)),
    sa.Column("cancelled_at", sa.DateTime(timezone=True)),
    sa.Column("owner", sa.String(120)),
    sa.Column("claimed_generation", sa.BigInteger),
    sa.Column("claimed_at", sa.DateTime(timezone=True)),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("failed_at", sa.DateTime(timezone=True)),
    # db_now: now() on PostgreSQL, SYSDATETIMEOFFSET() on SQL Server, whose CURRENT_TIMESTAMP carries no offset.
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now()),
)

OPEN = sa.and_(timers.c.fired_at.is_(None), timers.c.cancelled_at.is_(None), timers.c.failed_at.is_(None))
# The poller's scan of open timers by due time: partial on PostgreSQL, filtered on SQL Server, the same rows on both.
sa.Index("ix_timers_due_open", timers.c.due_at, postgresql_where=OPEN, mssql_where=OPEN)

# (base, kind) -> (node, interrupt id, delay in seconds): the timers a thread's waiting interrupts want.
Wanted = dict[tuple[str, str], tuple[str, str | None, float]]
Close = Literal["cancelled", "failed", "fired"]


def _in(delay_s: float) -> Any:
    return sa.func.now() + sa.func.make_interval(0, 0, 0, 0, 0, 0, delay_s)


def key_of(row: Any) -> tuple[str, str]:
    """(base, kind) of a timer row: its id without the restart counter."""
    base, kind, _ = str(row.timer_id).rsplit(":", 2)
    return base, kind


@dataclass(frozen=True)
class Claim:
    """The fire's claim transaction: `claimed` with the attempt count, or why it did not claim."""

    outcome: Literal["claimed", "duplicate", "cancelled", "not_waiting", "busy"]
    row: Any = None
    attempts: int = 0


class TimerStore:
    # Claims and closes are conditional updates (CAS) on the database's clock (CLOCK); a poller skips rows another
    # holds (LOCK); a fenced write and its fence check share one transaction (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset(
        {Guarantee.CAS, Guarantee.CLOCK, Guarantee.LOCK, Guarantee.TRANSACTION}
    )

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    @property
    def enabled(self) -> bool:
        return self.engine.dialect.name == "postgresql"

    async def sync(
        self, thread_id: str, wanted: Wanted, generation: int | None
    ) -> tuple[list[str], list[tuple[str, Any]]]:
        """Cancels the open timers not wanted (skipping rows another poller holds) and arms the wanted ones that never
        existed. Returns (cancelled ids, [(armed id, due at)])."""
        cancelled: list[str] = []
        armed: list[tuple[str, Any]] = []
        async with self.engine.begin() as c:
            # A superseded run's timer writes are refused in this transaction (ADR-0016); the new owner syncs them.
            await check_fence(c, thread_id, generation)
            rows = (await c.execute(timers.select().where(timers.c.thread_id == thread_id))).all()
            seen = {key_of(r) for r in rows}
            stale = [
                r.timer_id for r in rows if r.fired_at is None and r.cancelled_at is None and key_of(r) not in wanted
            ]
            if stale:
                locked = self._open(thread_id).where(timers.c.timer_id.in_(stale)).with_for_update(skip_locked=True)
                ids = [r.timer_id for r in (await c.execute(locked)).all()]
                cancelled.extend(ids)
                if ids:
                    await c.execute(
                        timers.update()
                        .where(timers.c.thread_id == thread_id, timers.c.timer_id.in_(ids))
                        .values(cancelled_at=sa.func.now())
                    )
            for (base, kind), (node, interrupt_id, delay) in wanted.items():
                # Never re-arm a timer that already fired or was cancelled for this interrupt.
                if (base, kind) not in seen:
                    armed.append(
                        await self._arm(
                            c,
                            thread_id,
                            f"{base}:{kind}:0",
                            kind=kind,
                            node=node,
                            interrupt_id=interrupt_id,
                            delay=delay,
                        )
                    )
        return cancelled, armed

    async def restart(self, thread_id: str, wanted: Wanted) -> list[tuple[str, str, Any]]:
        """Cancels each open wanted timer and arms its next round from now. Returns [(timer id, kind, due at)]."""
        out: list[tuple[str, str, Any]] = []
        async with self.engine.begin() as c:
            rows = (await c.execute(self._open(thread_id).with_for_update(skip_locked=True))).all()
            for r in rows:
                key = key_of(r)
                if key not in wanted:
                    continue
                n = int(str(r.timer_id).rsplit(":", 1)[1]) + 1
                node, interrupt_id, delay = wanted[key]
                await c.execute(
                    timers.update()
                    .where(timers.c.thread_id == thread_id, timers.c.timer_id == r.timer_id)
                    .values(cancelled_at=sa.func.now())
                )
                timer_id, due_at = await self._arm(
                    c,
                    thread_id,
                    f"{key[0]}:{key[1]}:{n}",
                    kind=key[1],
                    node=node,
                    interrupt_id=interrupt_id,
                    delay=delay,
                )
                out.append((timer_id, key[1], due_at))
        return out

    async def rows(self, thread_id: str) -> list[Any]:
        q = timers.select().where(timers.c.thread_id == thread_id).order_by(timers.c.created_at)
        async with self.engine.connect() as c:
            return list((await c.execute(q)).all())

    async def get(self, thread_id: str, timer_id: str) -> Any:
        """The timer with `is_due` from the database's clock, or None."""
        async with self.engine.connect() as c:
            return await self._get(c, thread_id, timer_id)

    async def claim(self, thread_id: str, timer_id: str, generation: int, *, waiting: bool) -> Claim:
        """Under the fire's lease: re-reads the timer, cancels it when its interrupt no longer waits, else claims it
        for this generation. `busy` when a claim of this or a newer generation exists."""
        async with self.engine.begin() as c:
            row = await self._get(c, thread_id, timer_id)
            if row is None or row.fired_at is not None or row.cancelled_at is not None or row.failed_at is not None:
                return Claim("duplicate" if row is not None and row.fired_at else "cancelled", row)
            if not waiting:
                await self._close(c, row, generation, cancelled_at=sa.func.now())
                return Claim("not_waiting", row)
            await check_fence(c, thread_id, generation)
            claimed = (
                await c.execute(
                    timers.update()
                    .where(
                        timers.c.thread_id == thread_id,
                        timers.c.timer_id == timer_id,
                        OPEN,
                        sa.or_(timers.c.claimed_generation.is_(None), timers.c.claimed_generation < generation),
                    )
                    .values(claimed_generation=generation, claimed_at=sa.func.now(), attempts=timers.c.attempts + 1)
                    .returning(timers.c.attempts)
                )
            ).first()
            return Claim("claimed", row, int(claimed.attempts)) if claimed is not None else Claim("busy", row)

    async def close(self, row: Any, generation: int | None, how: Close, *, owner: str | None = None) -> bool:
        """Marks an open timer cancelled, failed or fired, fenced by `generation`. False when it was not open."""
        values: dict[str, Any] = {f"{how}_at": sa.func.now()}
        if owner is not None:
            values["owner"] = owner
        async with self.engine.begin() as c:
            return await self._close(c, row, generation, **values)

    async def due(self, limit: int) -> list[tuple[str, str]]:
        q = (
            sa.select(timers.c.thread_id, timers.c.timer_id)
            .where(OPEN, timers.c.due_at <= sa.func.now())
            .order_by(timers.c.due_at)
            .limit(limit)
        )
        async with self.engine.connect() as c:
            return [(str(r.thread_id), str(r.timer_id)) for r in (await c.execute(q)).all()]

    async def open_due(self, thread_ids: list[str]) -> dict[str, dict[str, Any]]:
        """The earliest open breach and timeout due time per thread: {thread: {kind: due at}}."""
        if not thread_ids or not self.enabled:
            return {}
        q = sa.select(timers.c.thread_id, timers.c.kind, timers.c.due_at).where(
            timers.c.thread_id.in_(thread_ids), OPEN, timers.c.kind.in_(("breach", "timeout"))
        )
        found: dict[str, dict[str, Any]] = {}
        async with self.engine.connect() as c:
            for tid, kind, at in await c.execute(q):
                current = found.setdefault(str(tid), {}).get(str(kind))
                if current is None or at < current:
                    found[str(tid)][str(kind)] = at
        return found

    def _open(self, thread_id: str) -> sa.Select[Any]:
        return timers.select().where(timers.c.thread_id == thread_id, OPEN)

    async def _get(self, c: AsyncConnection, thread_id: str, timer_id: str) -> Any:
        q = sa.select(timers, (timers.c.due_at <= sa.func.now()).label("is_due")).where(
            timers.c.thread_id == thread_id, timers.c.timer_id == timer_id
        )
        return (await c.execute(q)).first()

    async def _close(self, c: AsyncConnection, row: Any, generation: int | None, **values: Any) -> bool:
        await check_fence(c, row.thread_id, generation)
        res = await c.execute(
            timers.update()
            .where(timers.c.thread_id == row.thread_id, timers.c.timer_id == row.timer_id, OPEN)
            .values(**values)
        )
        return res.rowcount == 1

    async def _arm(
        self,
        c: AsyncConnection,
        thread_id: str,
        timer_id: str,
        *,
        kind: str,
        node: str,
        interrupt_id: str | None,
        delay: float,
    ) -> tuple[str, Any]:
        new = (
            await c.execute(
                timers.insert()
                .values(
                    thread_id=thread_id,
                    timer_id=timer_id,
                    kind=kind,
                    node=node,
                    interrupt_id=interrupt_id,
                    due_at=_in(delay),
                )
                .returning(timers.c.timer_id, timers.c.due_at)
            )
        ).one()
        return str(new.timer_id), new.due_at
