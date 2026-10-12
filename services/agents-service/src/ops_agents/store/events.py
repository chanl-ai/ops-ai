"""The thread event log's table and queries. Each event is written as it happens at the thread's next `seq`, so a
client can re-attach from a cursor and a crashed run's events up to the crash survive. The event shapes are
`api/event_log.py`'s."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee

from .base import metadata
from .tenancy import current_tenant, tenant_tx

thread_events = sa.Table(
    "thread_events",
    metadata,
    sa.Column("position", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
    sa.Column("id", sa.String(40), nullable=False, unique=True),
    sa.Column("thread_id", sa.String(64), nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("run_id", sa.String(80)),
    sa.Column("type", sa.String(32), nullable=False),
    sa.Column("node", sa.String(120)),
    sa.Column("at", sa.String(32), nullable=False),
    sa.Column("data", sa.JSON),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, server_default="local", index=True),
    sa.UniqueConstraint("thread_id", "seq", name="uq_thread_events_thread_seq"),
)

# What the per-team stream carries: a thread's lifecycle, not its tokens and node steps.
LIFECYCLE = ("started", "waiting", "waiting_review", "decided", "finished", "failed")


def view(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "seq": row.seq,
        "type": row.type,
        "threadId": row.thread_id,
        "runId": row.run_id,
        "node": row.node,
        "at": row.at,
        "data": row.data,
    }


class EventLog:
    # Two appends that read the same last seq cannot both land: the unique (thread, seq) refuses the second, which
    # retries with the next one (CAS on insert).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def append(
        self,
        *,
        thread_id: str,
        team_id: str,
        run_id: str | None,
        type_: str,
        node: str | None = None,
        data: Any = None,
    ) -> dict[str, Any]:
        """Appends one event at the thread's next seq. Concurrent appends to one thread retry on the unique seq."""
        for _ in range(5):
            values = {
                "id": new_id("evt"),
                "thread_id": thread_id,
                "run_id": run_id,
                "type": type_,
                "node": node,
                "at": now_iso(),
                "data": data,
                "team_id": team_id,
            }
            # One statement: the next seq is read and written together, so an event costs one round trip.
            next_seq = (
                sa.select(sa.func.coalesce(sa.func.max(thread_events.c.seq), 0) + 1)
                .where(thread_events.c.thread_id == thread_id)
                .scalar_subquery()
            )
            stmt = thread_events.insert().values(**values, seq=next_seq).returning(thread_events.c.seq)
            try:
                async with tenant_tx(self.engine) as c:
                    seq = int((await c.execute(stmt)).scalar_one())
            except IntegrityError:
                continue
            return {k: values[k] for k in ("id", "type", "node", "at", "data")} | {
                "seq": seq,
                "threadId": thread_id,
                "runId": run_id,
            }
        raise RuntimeError(f"could not append an event to {thread_id} after 5 attempts")

    async def run_events(self, thread_id: str, run_id: str, after: int) -> list[dict[str, Any]]:
        q = (
            thread_events.select()
            .where(
                thread_events.c.thread_id == thread_id, thread_events.c.run_id == run_id, thread_events.c.seq > after
            )
            .order_by(thread_events.c.seq)
        )
        async with tenant_tx(self.engine) as c:
            return [view(r) for r in (await c.execute(q)).all()]

    async def team_events(self, team_id: str, after: int, limit: int = 200) -> list[tuple[int, dict[str, Any]]]:
        """Lifecycle events for a team after a stream position, with each event's position for the next cursor."""
        q = (
            thread_events.select()
            .where(
                thread_events.c.team_id == team_id,
                thread_events.c.tenant_id == current_tenant(),
                thread_events.c.position > after,
                thread_events.c.type.in_(LIFECYCLE),
            )
            .order_by(thread_events.c.position)
            .limit(limit)
        )
        async with tenant_tx(self.engine) as c:
            return [(int(r.position), view(r)) for r in (await c.execute(q)).all()]

    async def for_threads(self, thread_ids: list[str]) -> list[Any]:
        """Every event of the given threads, in seq order."""
        q = thread_events.select().where(thread_events.c.thread_id.in_(thread_ids)).order_by(thread_events.c.seq)
        async with tenant_tx(self.engine) as c:
            return list((await c.execute(q)).all())
