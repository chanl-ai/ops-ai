"""Service events (c-258): a named event a service emitted with a key, and the system workflow runs it started. One
row per event and key, so a repeat finds the first and a retry adds an attempt; `unhandled` when no system workflow
listens, kept so nothing a service reported is lost."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_engine.store.tables import engine_definitions, engine_runs
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.schema import TENANT_SCOPED
from ops_store.team_scope import team_visible

from .base import metadata
from .tenancy import current_tenant, tenant_tx

# started: listener runs began; resumed: no listener, but a step parked on it carried on (c-525); unhandled: neither.
Status = Literal["started", "resumed", "unhandled"]
EVENT_TRIGGER = "ops.trigger.event"

service_events = sa.Table(
    "service_events",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(120), nullable=False),
    sa.Column("event_key", sa.String(200), nullable=False),
    # The emitting service, from its token.
    sa.Column("source", sa.String(64), nullable=False),
    # The person the work is for, when the event names one.
    sa.Column("actor", sa.String(320)),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    # The runs the latest attempt started, one per listening system workflow.
    sa.Column("run_ids", sa.JSON, nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False),
    sa.Column("recorded_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    sa.UniqueConstraint("tenant_id", "name", "event_key", name="uq_service_events_key"),
    info=TENANT_SCOPED,
)


class ServiceEvents:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def get(self, name: str, key: str) -> dict[str, Any] | None:
        e = service_events
        async with tenant_tx(self.engine) as c:
            row = (
                (
                    await c.execute(
                        e.select().where(e.c.tenant_id == current_tenant(), e.c.name == name, e.c.event_key == key)
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def record(
        self, *, name: str, key: str, team_id: str, source: str, actor: str | None, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """The event's row, written the first time its key is seen; a repeat returns the stored row unchanged."""
        e = service_events
        now = now_iso()
        row: dict[str, Any] = {
            "id": new_id("sev"),
            "tenant_id": current_tenant(),
            "team_id": team_id,
            "name": name,
            "event_key": key,
            "source": source,
            "actor": actor,
            "payload": payload,
            "status": "unhandled",
            "run_ids": [],
            "attempts": 0,
            "recorded_at": now,
            "updated_at": now,
        }
        try:
            async with tenant_tx(self.engine) as c:
                await c.execute(e.insert().values(**row))
        except IntegrityError:
            # Seen before, or by a concurrent delivery of the same event: the stored row is the event.
            found = await self.get(name, key)
            assert found is not None
            return found
        return row

    async def started(self, event_id: str, *, status: Status, run_ids: list[str], attempts: int) -> None:
        e = service_events
        async with tenant_tx(self.engine) as c:
            await c.execute(
                e.update()
                .where(e.c.id == event_id)
                .values(status=status, run_ids=run_ids, attempts=attempts, updated_at=now_iso())
            )


def _event_of(definition: dict[str, Any] | None) -> str | None:
    nodes = cast(list[dict[str, Any]], (definition or {}).get("nodes") or [])
    for node in nodes:
        if node.get("type") == EVENT_TRIGGER:
            return str(cast(dict[str, Any], node.get("parameters") or {}).get("event") or "") or None
    return None


async def listeners(engine: AsyncEngine, name: str, workflow_id: str) -> list[dict[str, Any]]:
    """The live version of the tenant's handler for `name`: its no-team workflow `workflow_id`, while its Service event
    trigger still names the event. A team's workflow under that id or with that trigger is never the handler."""
    d = engine_definitions
    q = d.select().where(
        d.c.tenant_id == current_tenant(), d.c.stage == "live", d.c.workflow_id == workflow_id, d.c.team_id.is_(None)
    )
    async with tenant_tx(engine) as c:
        rows = [dict(r) for r in (await c.execute(q.order_by(d.c.workflow_id))).mappings()]
    return [r for r in rows if _event_of(cast(dict[str, Any], r["definition"])) == name]


async def attempts_of(engine: AsyncEngine, workflow_id: str, run_key: str) -> list[dict[str, Any]]:
    """The runs one event started in one workflow, first attempt first: `run_key`, then `run_key:2`, `:3`."""
    r = engine_runs
    q = sa.select(r.c.id, r.c.run_key, r.c.status, r.c.created_at).where(
        r.c.tenant_id == current_tenant(),
        team_visible(r),
        r.c.workflow_id == workflow_id,
        sa.or_(r.c.run_key == run_key, r.c.run_key.startswith(f"{run_key}:", autoescape=True)),
    )
    async with tenant_tx(engine) as c:
        rows = [dict(x) for x in (await c.execute(q)).mappings()]
    return sorted(rows, key=lambda x: (x["created_at"], x["run_key"]))
