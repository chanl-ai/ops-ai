"""The thread event log's table and queries. Each event is written as it happens at the thread's next `seq`, so a
client can re-attach from a cursor and a crashed run's events up to the crash survive. The event shapes are
`api/event_log.py`'s."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from ops_service_kit.http import Out
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.rows import rows
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import team_visible

from .base import metadata
from .leases import check_fence
from .tenancy import RuntimeStore, current_tenant

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
    sa.Index("ix_thread_events_run", "thread_id", "run_id", "seq"),
    # The team event poll, by tenant first: a team id is the same in every tenant.
    sa.Index("ix_thread_events_tenant_team_position", "tenant_id", "team_id", "position"),
    # Held to the caller's team by the database too (migration 0073).
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

# What the per-team stream carries: a thread's lifecycle, not its tokens and node steps.
LIFECYCLE = ("started", "waiting", "waiting_review", "decided", "finished", "failed")


class EventOut(Out):
    """One logged event. `wire()` is its stream form: the camelCase keys a client re-attaches with."""

    id: str
    seq: int
    type: str
    thread_id: str
    run_id: str | None
    node: str | None
    at: str
    data: Any

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude={"position"})


class TeamEventOut(EventOut):
    """A lifecycle event with its stream position, the next cursor of a team's stream."""

    position: int


_e = thread_events.c
EVENT_COLUMNS = (_e.id, _e.seq, _e.type, _e.thread_id, _e.run_id, _e.node, _e.at, _e.data)


class EventLog(RuntimeStore):
    # Two appends that read the same last seq cannot both land: the unique (thread, seq) refuses the second, which
    # retries with the next one (CAS on insert).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    async def append(
        self,
        *,
        thread_id: str,
        team_id: str,
        run_id: str | None,
        type_: str,
        node: str | None = None,
        data: Any = None,
        generation: int | None = None,
    ) -> EventOut:
        """Appends one event at the thread's next seq. Concurrent appends to one thread retry on the unique seq.
        `generation`: the writer's lease generation, checked in the same transaction (a workflow runner's worker)."""
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
                .where(thread_events.c.thread_id == thread_id, team_visible(thread_events))
                .scalar_subquery()
            )
            stmt = thread_events.insert().values(**values, seq=next_seq).returning(thread_events.c.seq)
            try:
                async with self.tx() as c:
                    await check_fence(c, thread_id, generation)
                    async with self.attempt(c):
                        seq = int((await c.execute(stmt)).scalar_one())
            except IntegrityError:
                continue
            return EventOut.model_validate({k: v for k, v in values.items() if k != "team_id"} | {"seq": seq})
        raise RuntimeError(f"could not append an event to {thread_id} after 5 attempts")

    async def run_events(self, thread_id: str, run_id: str, after: int) -> list[EventOut]:
        q = (
            sa.select(*EVENT_COLUMNS)
            .where(
                thread_events.c.thread_id == thread_id,
                thread_events.c.run_id == run_id,
                thread_events.c.seq > after,
                team_visible(thread_events),
            )
            .order_by(thread_events.c.seq)
        )
        async with self.tx() as c:
            return await rows(c, q, EventOut)

    async def team_events(self, team_id: str, after: int, limit: int = 200) -> list[TeamEventOut]:
        """Lifecycle events for a team after a stream position, with each event's position for the next cursor."""
        q = (
            sa.select(*EVENT_COLUMNS, _e.position)
            .where(
                thread_events.c.team_id == team_id,
                thread_events.c.tenant_id == current_tenant(),
                thread_events.c.position > after,
                thread_events.c.type.in_(LIFECYCLE),
                team_visible(thread_events),
            )
            .order_by(thread_events.c.position)
            .limit(limit)
        )
        async with self.tx() as c:
            return await rows(c, q, TeamEventOut)

    async def for_threads(self, thread_ids: list[str]) -> list[EventOut]:
        """Every event of the given threads, in seq order."""
        q = (
            sa.select(*EVENT_COLUMNS)
            .where(_e.thread_id.in_(thread_ids), team_visible(thread_events))
            .order_by(_e.seq, _e.position)
        )
        async with self.tx() as c:
            return await rows(c, q, EventOut)
