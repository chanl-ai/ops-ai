"""What a workflow's trigger received (c-201): one row per message read, with the run it started or why it started
none. Rows are only ever added; the list is what shows a filtered message, a caught redelivery or a capped day."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import team_visible

from .base import metadata
from .tenancy import current_tenant, tenant_tx

# cursor_reset: no message. The mailbox refused the stored read position, so mail that arrived since the last read was
# skipped and reading starts again at the folder's end.
# start_failed: starting the message's run raised; the next read tries it again. set_aside: it failed SET_ASIDE_AFTER
# reads, so reading went on past it and the row keeps the message for Run again (c-561).
Outcome = Literal["started", "duplicate", "filtered", "daily_cap", "cursor_reset", "start_failed", "set_aside"]
SET_ASIDE_AFTER = 3
# How long a set-aside message is kept for Run again: raw mail is not held for ever.
KEEP_SET_ASIDE_DAYS = 30

trigger_events = sa.Table(
    "trigger_events",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("workflow_id", sa.String(200), nullable=False),
    # email:<mailbox address>
    sa.Column("source", sa.String(320), nullable=False),
    # The run key the event maps to; equal for every delivery of one message.
    sa.Column("event_key", sa.String(200), nullable=False),
    sa.Column("sender", sa.String(320), nullable=False),
    sa.Column("subject", sa.String(500), nullable=False),
    sa.Column("received_at", sa.String(40), nullable=False),
    sa.Column("outcome", sa.String(16), nullable=False),
    sa.Column("run_id", sa.String(64)),
    sa.Column("detail", sa.Text(), nullable=False),
    sa.Column("recorded_at", sa.String(32), nullable=False),
    # A set-aside message as read (c-561), JSON, for Run again; cleared once its run starts or after 30 days. Never
    # listed: it holds the whole mail, attachments included.
    sa.Column("item", sa.Text()),
    sa.Index("ix_trigger_events_workflow", "tenant_id", "workflow_id", "recorded_at"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


@dataclass(frozen=True)
class TriggerEvent:
    team_id: str
    workflow_id: str
    source: str
    event_key: str
    sender: str
    subject: str
    received_at: str
    outcome: Outcome
    run_id: str | None = None
    detail: dict[str, Any] | None = None
    item: str | None = None


# Every column but the kept message: what the trigger list shows.
LISTED = [c for c in trigger_events.c if c.name != "item"]


class TriggerEvents:
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def add(self, e: TriggerEvent) -> None:
        values = {
            "id": new_id("tev"),
            "team_id": e.team_id,
            "workflow_id": e.workflow_id,
            "source": e.source[:320],
            "event_key": e.event_key,
            "sender": e.sender[:320],
            "subject": e.subject[:500],
            "received_at": e.received_at[:40],
            "outcome": e.outcome,
            "run_id": e.run_id,
            "detail": json.dumps(e.detail or {}),
            "recorded_at": now_iso(),
            "item": e.item,
        }
        async with tenant_tx(self.engine) as c:
            await c.execute(trigger_events.insert().values(**values))

    async def started_since(self, workflow_id: str, since: str) -> int:
        """Runs the workflow's trigger started at or after `since`: what its daily cap counts."""
        t = trigger_events
        q = sa.select(sa.func.count()).where(
            t.c.tenant_id == current_tenant(),
            t.c.workflow_id == workflow_id,
            t.c.outcome == "started",
            t.c.recorded_at >= since,
        )
        async with tenant_tx(self.engine) as c:
            return int((await c.execute(q)).scalar_one())

    async def page(
        self, workflow_id: str, *, team_id: str, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        """The workflow's events in `team_id`, newest first, with the total."""
        t = trigger_events
        where = (
            t.c.tenant_id == current_tenant(),
            t.c.team_id == team_id,
            t.c.workflow_id == workflow_id,
            team_visible(t),
        )
        q = sa.select(*LISTED).where(*where).order_by(t.c.recorded_at.desc(), t.c.id.desc())
        async with tenant_tx(self.engine) as c:
            total = int((await c.execute(sa.select(sa.func.count()).select_from(t).where(*where))).scalar_one())
            rows = (await c.execute(q.limit(page_size).offset((page - 1) * page_size))).mappings().all()
        return [dict(r) | {"detail": json.loads(r["detail"] or "{}")} for r in rows], total

    async def failures(self, workflow_id: str, event_key: str) -> tuple[int, bool]:
        """The reads on which starting this message's run failed, and whether it was set aside."""
        t = trigger_events
        q = sa.select(
            sa.func.count().filter(t.c.outcome == "start_failed"), sa.func.count().filter(t.c.outcome == "set_aside")
        ).where(
            t.c.tenant_id == current_tenant(),
            t.c.workflow_id == workflow_id,
            t.c.event_key == event_key,
            t.c.outcome.in_(("start_failed", "set_aside")),
            team_visible(t),
        )
        async with tenant_tx(self.engine) as c:
            failed, aside = (await c.execute(q)).one()
        return int(failed), int(aside) > 0

    async def set_aside(self, event_id: str) -> dict[str, Any] | None:
        """A set-aside event the caller's team may see, with its kept message; None when there is none, or its message
        was already run or forgotten."""
        t = trigger_events
        q = sa.select(t).where(
            t.c.tenant_id == current_tenant(),
            t.c.id == event_id,
            t.c.outcome == "set_aside",
            t.c.item.is_not(None),
            team_visible(t),
        )
        async with tenant_tx(self.engine) as c:
            row = (await c.execute(q)).mappings().one_or_none()
        return dict(row) if row is not None else None

    async def forget(self, event_id: str) -> None:
        """Drops the kept message once its run has started."""
        t = trigger_events
        async with tenant_tx(self.engine) as c:
            await c.execute(t.update().where(t.c.tenant_id == current_tenant(), t.c.id == event_id).values(item=None))

    async def forget_before(self, workflow_id: str, before: str) -> None:
        """Drops the messages the workflow set aside before `before`."""
        t = trigger_events
        async with tenant_tx(self.engine) as c:
            await c.execute(
                t.update()
                .where(
                    t.c.tenant_id == current_tenant(),
                    t.c.workflow_id == workflow_id,
                    t.c.recorded_at < before,
                    t.c.outcome == "set_aside",
                    t.c.item.is_not(None),
                    team_visible(t),
                )
                .values(item=None)
            )
