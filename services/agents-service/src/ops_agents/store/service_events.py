"""Service events: a named event a service emitted with a key, and the system workflow runs it started. One
row per event and key, so a repeat finds the first and a retry adds an attempt; `unhandled` when no system workflow
listens, kept so nothing a service reported is lost."""

from __future__ import annotations

from typing import ClassVar, Literal, TypedDict, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_engine.store import DefinitionRow
from ops_engine.store.tables import engine_definitions, engine_runs
from ops_service_kit.http import Json, JsonValue, Out
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.rows import one, rows
from ops_store.schema import TENANT_SCOPED
from ops_store.team_scope import team_visible

from .base import metadata
from .tenancy import current_tenant, tenant_tx

# started: listener runs began; resumed: no listener, but a step parked on it carried on; unhandled: neither.
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


class ServiceEventRow(Out):
    """One event, every column of `service_events` in column order. `status` stays a plain string and the JSON
    columns stay any JSON, so every stored row reads as it did; the payload is the reporting service's own data."""

    id: str
    tenant_id: str
    team_id: str
    name: str
    event_key: str
    source: str
    actor: str | None
    payload: JsonValue
    status: str
    run_ids: JsonValue
    attempts: int
    recorded_at: str
    updated_at: str


class _AttemptRow(Out):
    id: str
    run_key: str
    status: str
    created_at: str


class RunAttempt(TypedDict):
    """One run an event started in one workflow, in the selected columns' order."""

    id: str
    run_key: str
    status: str
    created_at: str


class ServiceEvents:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def get(self, name: str, key: str) -> ServiceEventRow | None:
        e = service_events
        async with tenant_tx(self.engine) as c:
            return await one(
                c,
                e.select().where(e.c.tenant_id == current_tenant(), e.c.name == name, e.c.event_key == key),
                ServiceEventRow,
            )

    async def record(
        self, *, name: str, key: str, team_id: str, source: str, actor: str | None, payload: Json
    ) -> ServiceEventRow:
        """The event's row, written the first time its key is seen; a repeat returns the stored row unchanged."""
        e = service_events
        now = now_iso()
        row: Json = {
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
        # Not validated: the row is what was just written, and the payload goes on as the caller's own object, whatever
        # JSON column accepted it (a tuple, a number key), as the written row always did.
        return ServiceEventRow.model_construct(None, **row)

    async def started(self, event_id: str, *, status: Status, run_ids: list[str], attempts: int) -> None:
        e = service_events
        async with tenant_tx(self.engine) as c:
            await c.execute(
                e.update()
                .where(e.c.id == event_id)
                .values(status=status, run_ids=run_ids, attempts=attempts, updated_at=now_iso())
            )


def _event_of(definition: Json | None) -> str | None:
    nodes = cast(list[Json], (definition or {}).get("nodes") or [])
    for node in nodes:
        if node.get("type") == EVENT_TRIGGER:
            return str(cast(Json, node.get("parameters") or {}).get("event") or "") or None
    return None


async def listeners(engine: AsyncEngine, name: str, workflow_id: str) -> list[DefinitionRow]:
    """The live version of the tenant's handler for `name`: its no-team workflow `workflow_id`, while its Service event
    trigger still names the event. A team's workflow under that id or with that trigger is never the handler."""
    d = engine_definitions
    q = d.select().where(
        d.c.tenant_id == current_tenant(), d.c.stage == "live", d.c.workflow_id == workflow_id, d.c.team_id.is_(None)
    )
    async with tenant_tx(engine) as c:
        found = await rows(c, q.order_by(d.c.workflow_id), DefinitionRow)
    return [r for r in found if _event_of(r.definition) == name]


async def attempts_of(engine: AsyncEngine, workflow_id: str, run_key: str) -> list[RunAttempt]:
    """The runs one event started in one workflow, first attempt first: `run_key`, then `run_key:2`, `:3`."""
    r = engine_runs
    q = sa.select(r.c.id, r.c.run_key, r.c.status, r.c.created_at).where(
        r.c.tenant_id == current_tenant(),
        team_visible(r),
        r.c.workflow_id == workflow_id,
        sa.or_(r.c.run_key == run_key, r.c.run_key.startswith(f"{run_key}:", autoescape=True)),
    )
    async with tenant_tx(engine) as c:
        found = [
            RunAttempt(id=x.id, run_key=x.run_key, status=x.status, created_at=x.created_at)
            for x in await rows(c, q, _AttemptRow)
        ]
    return sorted(found, key=lambda x: (x["created_at"], x["run_key"]))
