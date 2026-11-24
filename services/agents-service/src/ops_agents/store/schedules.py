"""Saved schedules: one row per workflow and trigger step, outside the workflow's versions, so a save applies at once
to whatever version is live and going live, archive and restore write nothing here. The builder writes the rule and
who changed it; the schedule clock alone writes the slot state beside it (`rule_digest`, `last_slot_at`,
`last_outcome`, `last_run_id`, `seen_at`). `seen_at` is when the clock first saw the schedule live with this rule, and
is null while the workflow is not live or has lost the step, so a schedule's first sighting is read from the row, not
from any one machine's memory. Deleting the workflow deletes its rows.

The slot write names the last slot it read and changes the row only while that is still the stored one, so of two
machines on one slot exactly one records its outcome; the run key (`schedule:{workflow}:{slot}`) keeps the runs to one
as well."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, ClassVar

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import now_iso
from ops_store import Guarantee, isolation
from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import SCHEDULE_TENANTS, current_tenant, system_tx, tenant_tx

Rule = dict[str, JsonValue]
# What the clock records for a slot.
OUTCOMES = ("ran", "late", "skipped", "refused", "missed", "seen")

workflow_schedules = sa.Table(
    "workflow_schedules",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
    sa.Column("workflow_id", sa.String(64), primary_key=True),
    # The trigger step's id in the definition; the row never names a node type.
    sa.Column("trigger_step", sa.String(100), primary_key=True),
    # The workflow's team when saved: a workflow no team owns cannot carry a schedule.
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("rule", sa.JSON, nullable=False),
    sa.Column("changed_by", sa.String(200), nullable=False),
    sa.Column("changed_at", sa.String(32), nullable=False),
    sa.Column("rule_digest", sa.String(64), nullable=True),
    sa.Column("last_slot_at", sa.String(32), nullable=True),
    sa.Column("last_outcome", sa.String(16), nullable=True),
    sa.Column("last_run_id", sa.String(64), nullable=True),
    sa.Column("seen_at", sa.String(32), nullable=True),
    info=TENANT_SCOPED,
)


@dataclass(frozen=True)
class ScheduleRow:
    workflow_id: str
    trigger_step: str
    team_id: str
    rule: Rule
    changed_by: str
    changed_at: str
    rule_digest: str | None
    last_slot_at: str | None
    last_outcome: str | None
    last_run_id: str | None
    seen_at: str | None


def _row(r: Any) -> ScheduleRow:
    return ScheduleRow(**{f.name: getattr(r, f.name) for f in fields(ScheduleRow)})


class WorkflowSchedules:
    # Saves are last-writer-wins on the rule; the slot write is conditional on the slot it read (see the module note).
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    def _key(self, workflow_id: str, trigger_step: str) -> sa.ColumnElement[bool]:
        t = workflow_schedules
        return sa.and_(
            t.c.tenant_id == current_tenant(), t.c.workflow_id == workflow_id, t.c.trigger_step == trigger_step
        )

    async def get(self, workflow_id: str, trigger_step: str) -> ScheduleRow | None:
        t = workflow_schedules
        cols = [c for c in t.c if c.name != "tenant_id"]
        async with tenant_tx(self.engine) as c:
            row = (await c.execute(sa.select(*cols).where(self._key(workflow_id, trigger_step)))).first()
        return _row(row) if row else None

    async def for_workflow(self, workflow_id: str) -> list[ScheduleRow]:
        t = workflow_schedules
        cols = [c for c in t.c if c.name != "tenant_id"]
        q = sa.select(*cols).where(t.c.tenant_id == current_tenant(), t.c.workflow_id == workflow_id)
        async with tenant_tx(self.engine) as c:
            return [_row(r) for r in await c.execute(q.order_by(t.c.trigger_step))]

    async def for_workflows(self, workflow_ids: list[str]) -> list[ScheduleRow]:
        """The saved schedules of these workflows only, for a page that shows the ones it lists."""
        if not workflow_ids:
            return []
        t = workflow_schedules
        cols = [c for c in t.c if c.name != "tenant_id"]
        q = sa.select(*cols).where(t.c.tenant_id == current_tenant(), t.c.workflow_id.in_(workflow_ids))
        async with tenant_tx(self.engine) as c:
            return [_row(r) for r in await c.execute(q.order_by(t.c.workflow_id, t.c.trigger_step))]

    async def everything(self) -> list[ScheduleRow]:
        """Every saved schedule of the acting tenant, for the clock, which reads them beside the live versions."""
        t = workflow_schedules
        cols = [c for c in t.c if c.name != "tenant_id"]
        q = sa.select(*cols).where(t.c.tenant_id == current_tenant()).order_by(t.c.workflow_id, t.c.trigger_step)
        async with tenant_tx(self.engine) as c:
            return [_row(r) for r in await c.execute(q)]

    async def tenants(self) -> list[str]:
        """Every tenant holding a saved schedule, read past row-level security: the clock visits a tenant whose only
        scheduled workflow is paused, to mark its schedule idle, and then works each tenant under its own."""
        t = workflow_schedules
        async with system_tx(self.engine, SCHEDULE_TENANTS) as c:
            return list((await c.execute(sa.select(t.c.tenant_id).distinct())).scalars())

    async def idle(self, workflow_id: str, trigger_step: str) -> None:
        """The clock found the workflow not live, or its live version without the step: the next time it is seen live
        is a first sighting."""
        t = workflow_schedules
        async with tenant_tx(self.engine) as c:
            await c.execute(t.update().where(self._key(workflow_id, trigger_step)).values(seen_at=None))

    async def sighted(self, workflow_id: str, trigger_step: str, *, expected: str | None, digest: str, at: str) -> bool:
        """A first sighting with no slot yet (a rule whose first slot is ahead): the rule it was seen with and when,
        with the last slot left as it was, only while that is still `expected`."""
        t = workflow_schedules
        same = t.c.last_slot_at.is_(None) if expected is None else t.c.last_slot_at == expected
        async with tenant_tx(self.engine) as c:
            done = await c.execute(
                t.update().where(self._key(workflow_id, trigger_step), same).values(rule_digest=digest, seen_at=at)
            )
        return done.rowcount == 1

    async def save(self, workflow_id: str, trigger_step: str, team_id: str, rule: Rule, by: str) -> Rule | None:
        """Saves the builder's rule and returns the one it replaced (None for a new schedule); the slot state stays,
        and the clock treats the changed rule as a first sighting."""
        t = workflow_schedules
        values = {"team_id": team_id, "rule": rule, "changed_by": by, "changed_at": now_iso()}
        before = await self.get(workflow_id, trigger_step)
        if before is None:
            try:
                async with tenant_tx(self.engine) as c, isolation.attempt(c):
                    await c.execute(t.insert().values(workflow_id=workflow_id, trigger_step=trigger_step, **values))
                return None
            except IntegrityError:
                before = await self.get(workflow_id, trigger_step)
        async with tenant_tx(self.engine) as c:
            await c.execute(t.update().where(self._key(workflow_id, trigger_step)).values(**values))
        return before.rule if before else None

    async def clear(self, workflow_id: str, trigger_step: str) -> bool:
        async with tenant_tx(self.engine) as c:
            done = await c.execute(workflow_schedules.delete().where(self._key(workflow_id, trigger_step)))
        return done.rowcount > 0

    async def delete_workflow(self, workflow_id: str) -> None:
        t = workflow_schedules
        async with tenant_tx(self.engine) as c:
            await c.execute(t.delete().where(t.c.tenant_id == current_tenant(), t.c.workflow_id == workflow_id))

    async def record_slot(
        self,
        workflow_id: str,
        trigger_step: str,
        *,
        expected: str | None,
        slot: str,
        outcome: str,
        digest: str,
        run_id: str | None,
        at: str | None = None,
    ) -> bool:
        """Records `slot` and its outcome, seen on the pass at `at`, only while the stored last slot is still
        `expected`; False when another machine moved it first."""
        if outcome not in OUTCOMES:
            raise ValueError(f"{outcome} is not a slot outcome")
        t = workflow_schedules
        same = t.c.last_slot_at.is_(None) if expected is None else t.c.last_slot_at == expected
        values = {
            "last_slot_at": slot,
            "last_outcome": outcome,
            "rule_digest": digest,
            "last_run_id": run_id,
            "seen_at": at or now_iso(),
        }
        async with tenant_tx(self.engine) as c:
            done = await c.execute(t.update().where(self._key(workflow_id, trigger_step), same).values(**values))
        return done.rowcount == 1
