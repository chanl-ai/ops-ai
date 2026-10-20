"""Widget deployments (c-117): an agent's chat served to pages on other origins. Each pins the published agent version
it serves and lists the exact origins allowed to use it; the team that owns it is the team its conversations belong
to. Origins are JSON kept whole and never queried (database portability D5)."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import Guarantee
from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import current_tenant, tenant_tx

widget_deployments = sa.Table(
    "widget_deployments",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, server_default="local", index=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("agent_id", sa.String(64), nullable=False),
    # None: the agent's newest published version, read when a conversation starts (c-245, "Latest").
    sa.Column("agent_version", sa.Integer, nullable=True),
    # ["https://intranet.bank.example", ...]: exact scheme://host[:port], no wildcards.
    sa.Column("origins", sa.JSON, nullable=False),
    sa.Column("paused", sa.Boolean, nullable=False, default=False),
    # Set once and never cleared (c-130): a retired embed answers no page again.
    sa.Column("retired_at", sa.String(32), nullable=True),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    info=TENANT_SCOPED,
)


class WidgetDeployments:
    # Retiring is a compare-and-set on `retired_at` being empty, so two retires record one time.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def add(self, row: dict[str, Any]) -> None:
        async with tenant_tx(self.engine) as c:
            await c.execute(widget_deployments.insert().values(**row))

    async def get(self, deployment_id: str) -> dict[str, Any] | None:
        q = widget_deployments.select().where(
            widget_deployments.c.id == deployment_id, widget_deployments.c.tenant_id == current_tenant()
        )
        async with tenant_tx(self.engine) as c:
            r = (await c.execute(q)).mappings().first()
        return dict(r) if r is not None else None

    async def for_team(self, team_id: str | None) -> list[dict[str, Any]]:
        q = widget_deployments.select().where(widget_deployments.c.tenant_id == current_tenant())
        if team_id is not None:
            q = q.where(widget_deployments.c.team_id == team_id)
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q.order_by(widget_deployments.c.created_at.desc()))).mappings()]

    async def update(self, deployment_id: str, **values: Any) -> None:
        q = (
            widget_deployments.update()
            .where(widget_deployments.c.id == deployment_id, widget_deployments.c.tenant_id == current_tenant())
            .values(**values)
        )
        async with tenant_tx(self.engine) as c:
            await c.execute(q)

    async def retire(self, deployment_id: str, at: str) -> bool:
        """False when the embed was retired already."""
        q = (
            widget_deployments.update()
            .where(
                widget_deployments.c.id == deployment_id,
                widget_deployments.c.tenant_id == current_tenant(),
                widget_deployments.c.retired_at.is_(None),
            )
            .values(retired_at=at, updated_at=at)
        )
        async with tenant_tx(self.engine) as c:
            return (await c.execute(q)).rowcount == 1
