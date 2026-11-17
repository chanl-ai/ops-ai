"""This service's copy of tools-service's catalogue (`ops_store.copies`), kept by its `tool.module.*` and
`tool.team_state.changed` events and repaired by a resync of `GET /v1/tool-catalog`, so a tools list reads it in one
transaction instead of asking tools-service per request.

- `tool_catalog`: one row per module of the tenant, keyed by tenant and module id. `owner_team` is the team that owns
  it, null for a workspace-level module every team reads; the event's team only routed delivery.
- `tool_catalog_operations`: the module's served operations, one row each, rewritten in the transaction that applied
  the module's event, and only when that event is the one the module row now holds.
- `tool_team_state`: one team's grant of a module it does not own (id `approval:<module id>`), keyed by tenant, team
  and id; `expires_at` is ISO time, and a grant past it is not shown.

A copy answers what to show; whether a caller may run a tool is always asked of tools-service.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, cast

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.http import Out
from ops_service_kit.ids import now_iso
from ops_store import Guarantee, background, copies
from ops_store.outbox import Event, ToolChanged, ToolPublished, ToolTeamStateChanged
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED

from .base import metadata
from .tenancy import RuntimeStore, current_tenant

# The events this copy is kept by, as tools-service names them.
MODULE_EVENTS = (ToolPublished.model_fields["kind"].default, ToolChanged.model_fields["kind"].default)
GRANT_EVENT = ToolTeamStateChanged.model_fields["kind"].default
COPIED = frozenset({*MODULE_EVENTS, GRANT_EVENT})

tool_catalog = copies.copy_table(
    metadata,
    "tool_catalog",
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("title", sa.String(200), nullable=True),
    sa.Column("app", sa.String(200), nullable=True),
    sa.Column("owner_team", sa.String(64), nullable=True),
    sa.Column("status", sa.String(32), nullable=True),
    sa.Column("version", sa.String(64), nullable=True),
    marking=TENANT_SCOPED,
)
sa.Index("ix_tool_catalog_owner_team", tool_catalog.c.tenant_id, tool_catalog.c.owner_team)

tool_catalog_operations = sa.Table(
    "tool_catalog_operations",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("module_id", sa.String(200), primary_key=True),
    sa.Column("id", sa.String(200), primary_key=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("access", sa.String(16), nullable=False),
    sa.Column("requires_approval", sa.Boolean, nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False),
    # The tools list sorts by name, then the key, so pages never repeat or skip a row.
    sa.Index("ix_tool_catalog_operations_name", "tenant_id", "name", "module_id", "id"),
    info=TENANT_SCOPED,
)

tool_team_state = copies.copy_table(
    metadata,
    "tool_team_state",
    sa.Column("module_id", sa.String(200), nullable=False),
    sa.Column("via", sa.String(32), nullable=False),
    sa.Column("operations", sa.JSON, nullable=False),
    sa.Column("expires_at", sa.String(40), nullable=True),
    marking={**TENANT_SCOPED, **TEAM_OWNED},
)
sa.Index(
    "ix_tool_team_state_module", tool_team_state.c.tenant_id, tool_team_state.c.team_id, tool_team_state.c.module_id
)

# The catalogue resync: tools-service lists one tenant per call, so a pass works each tenant this service holds.
RESYNC_KEY = "tool_catalog_resync"
RESYNC_EVERY_S = 3600.0
RESYNC = background.register(
    background.Process(
        RESYNC_KEY,
        "agents",
        "Copy of the tool catalogue",
        "Reads tools-service's catalogue for each workspace and applies what events missed to tool_catalog.",
        RESYNC_EVERY_S,
        "tools-service lists one workspace's catalogue, every team's; each workspace is applied as itself.",
    )
)


@dataclass(frozen=True)
class CopiedTool:
    """One operation of a module the team may see, as the copy holds it."""

    module_id: str
    module_name: str
    module_title: str | None
    app: str | None
    owner_team: str | None
    operation_id: str
    name: str
    access: str
    requires_approval: bool
    enabled: bool
    # The grant the team reads it through, when it does not own it and it is not workspace-level.
    granted: tuple[str, ...] | None


def wired_event(name: str, team_id: str, payload: Mapping[str, JsonValue], *, tenant_id: str) -> Event:
    """A catalogue event as `POST /v1/events` receives it: `ops_store.outbox.add` sends the payload with the event's
    revision inside it, and the tenant is the token's."""
    body = dict(payload)
    revision = body.pop("revision", None)
    return Event.model_validate(
        {"name": name, "tenantId": tenant_id, "teamId": team_id, "revision": revision, "payload": body}
    )


class CatalogPage(Out):
    """One page of tools-service's `GET /v1/tool-catalog`: the events that build one tenant's copy."""

    items: list[Event]
    next_cursor: str | None


class ToolCopies(RuntimeStore):
    # An event's guarded writes (`copies.apply`, CAS) and the module's operations land together.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    async def apply(self, events: Sequence[Event]) -> None:
        """Applies each event in one transaction of the current tenant: a module event to `tool_catalog` and its
        operations, a grant event to `tool_team_state`; an older or equal revision changes nothing and a delete keeps
        the row as its tombstone."""
        async with self.tx() as c:
            for event in events:
                await self.apply_on(c, event)

    async def apply_on(self, c: AsyncConnection, event: Event) -> None:
        payload = event.payload
        if isinstance(payload, ToolTeamStateChanged):
            await copies.apply(c, tool_team_state, event)
            return
        if not isinstance(payload, ToolPublished | ToolChanged):
            raise ValueError(f"{event.name} is not a tool catalogue event")
        t = tool_catalog.c
        held = sa.select(t.revision, t.deleted).where(t.tenant_id == event.tenant_id, t.id == payload.id)

        async def pair() -> tuple[int, bool] | None:
            row = (await c.execute(held)).first()
            return None if row is None else (int(row.revision), bool(row.deleted))

        before = await pair()
        await copies.apply(c, tool_catalog, event)
        # The operations follow only an event that moved the module row: a replay, or one at or below what the row
        # held, finds it already at that pair or elsewhere and leaves them alone.
        ours = (event.revision, payload.deleted)
        if before == ours or await pair() != ours:
            return
        o = tool_catalog_operations
        await c.execute(o.delete().where(o.c.tenant_id == event.tenant_id, o.c.module_id == payload.id))
        if payload.deleted or not payload.operations:
            return
        await c.execute(
            o.insert(),
            [
                {
                    "tenant_id": event.tenant_id,
                    "module_id": payload.id,
                    "id": op.id,
                    "name": op.name,
                    "access": op.access,
                    "requires_approval": op.requires_approval,
                    "enabled": op.enabled,
                }
                for op in payload.operations
            ],
        )

    async def visible(self, team: str | None) -> list[CopiedTool]:
        """Every live operation `team` may see in the current tenant, by name then key: its own modules,
        workspace-level ones, and modules another team granted it whose grant has not ended. One row per name, since a
        grant names a tool by name: the team's own module first (its copy of a built-in app is the one a call resolves
        to, as tools-service's grantable list decides), then a workspace-level one, then a granted one, the lowest
        module id within each. Names its tenant and team itself; the row policies hold it to them as well."""
        m, o, g = tool_catalog, tool_catalog_operations, tool_team_state
        tenant = current_tenant()
        grant = (
            sa.select(g.c.module_id, g.c.operations)
            .where(
                g.c.tenant_id == tenant,
                g.c.team_id == team,
                copies.live(g),
                sa.or_(g.c.expires_at.is_(None), g.c.expires_at > now_iso()),
            )
            .subquery("grant")
        )
        q = (
            sa.select(
                m.c.id,
                m.c.name,
                m.c.title,
                m.c.app,
                m.c.owner_team,
                o.c.id.label("op_id"),
                o.c.name.label("op_name"),
                o.c.access,
                o.c.requires_approval,
                o.c.enabled,
                grant.c.operations,
            )
            .select_from(
                m.join(o, sa.and_(o.c.tenant_id == m.c.tenant_id, o.c.module_id == m.c.id)).outerjoin(
                    grant, grant.c.module_id == m.c.id
                )
            )
            .where(
                m.c.tenant_id == tenant,
                copies.live(m),
                sa.or_(m.c.owner_team.is_(None), m.c.owner_team == team, grant.c.module_id.is_not(None)),
            )
            .order_by(o.c.name, o.c.module_id, o.c.id)
        )
        async with self.tx() as c:
            rows = (await c.execute(q)).all()
        out: dict[str, CopiedTool] = {}
        for r in rows:
            mine = r.owner_team is None or r.owner_team == team
            ops = None if mine else tuple(str(n) for n in cast(list[object], r.operations or []))
            if ops is not None and r.op_name not in ops:
                continue  # a grant covers the operations it names
            held = out.get(str(r.op_name))
            if held is not None and _rank(held, team) <= _rank_of(r.owner_team, ops, team):
                continue
            out[str(r.op_name)] = CopiedTool(
                str(r.id),
                str(r.name),
                r.title,
                r.app,
                r.owner_team,
                str(r.op_id),
                str(r.op_name),
                str(r.access),
                bool(r.requires_approval),
                bool(r.enabled),
                ops,
            )
        return sorted(out.values(), key=lambda t: (t.name, t.module_id, t.operation_id))


def _rank_of(owner_team: str | None, granted: tuple[str, ...] | None, team: str | None) -> int:
    """Which of two modules serving one name a team reads: 0 its own, 1 workspace-level, 2 granted by another team."""
    if granted is not None:
        return 2
    return 0 if owner_team is not None and owner_team == team else 1


def _rank(tool: CopiedTool, team: str | None) -> int:
    return _rank_of(tool.owner_team, tool.granted, team)
