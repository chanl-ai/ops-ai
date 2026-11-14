"""MCP links: a named address for a chosen set of one team's tools and published workflows.

A link is a filter on the team's MCP door, never a second server: `/mcp/<team>/<slug>` lists only the link's tools and
refuses any other, and every call through it is one gateway call logged with the link's id (gateway_calls.link_id).
Who may connect and what a call may do stay the door's and the gateway's.
"""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.errors import Unprocessable
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee, isolation
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import team_visible

from .connections import ROLE
from .modules import metadata

mcp_links = sa.Table(
    "mcp_links",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),
    # The last part of the link's address; unique in its team, so one address names one link.
    sa.Column("slug", sa.String(64), nullable=False),
    sa.Column("name", sa.String(120), nullable=False),
    # Always "test" while outside assistants reach test data only; production is turned on per install later.
    sa.Column("environment", sa.String(16), nullable=False),
    # The picked tools: [{"name": <tool or workflow__<id>>, "kind": "tool" | "workflow", "title", "access"}].
    sa.Column("tools", sa.JSON, nullable=False),
    sa.Column("paused", sa.Boolean, nullable=False),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    sa.UniqueConstraint("tenant_id", "team_id", "slug", name="uq_mcp_links_team_slug"),
    # Held to its team by the database (tools_0079): only a transaction run as ROLE in the link's team sees it.
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


def _row(r: Any) -> dict[str, Any]:
    return dict(r._mapping)  # pyright: ignore[reportPrivateUsage]


class McpLinks:
    # A slug is unique per team by constraint, so two creates of the same name cannot both win.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def list(self, tenant_id: str, team_id: str) -> list[dict[str, Any]]:
        t = mcp_links
        with isolation.scope(tenant_id, team_id):
            q = sa.select(t).where(t.c.tenant_id == tenant_id, team_visible(t), t.c.team_id == team_id)
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                return [_row(r) for r in await c.execute(q.order_by(t.c.name))]

    async def get(self, tenant_id: str, team_id: str, link_id: str) -> dict[str, Any] | None:
        t = mcp_links
        with isolation.scope(tenant_id, team_id):
            q = sa.select(t).where(t.c.tenant_id == tenant_id, team_visible(t), t.c.id == link_id)
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                found = (await c.execute(q)).first()
        return _row(found) if found else None

    async def by_slug(self, tenant_id: str, team_id: str, slug: str) -> dict[str, Any] | None:
        t = mcp_links
        with isolation.scope(tenant_id, team_id):
            q = sa.select(t).where(
                t.c.tenant_id == tenant_id, team_visible(t), t.c.team_id == team_id, t.c.slug == slug
            )
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                found = (await c.execute(q)).first()
        return _row(found) if found else None

    async def create(
        self, tenant_id: str, team_id: str, *, slug: str, name: str, tools: list[dict[str, Any]], by: str
    ) -> dict[str, Any]:
        at = now_iso()
        row = {
            "id": new_id("mcl"),
            "tenant_id": tenant_id,
            "team_id": team_id,
            "slug": slug,
            "name": name,
            "environment": "test",
            "tools": tools,
            "paused": False,
            "created_by": by,
            "created_at": at,
            "updated_at": at,
        }
        try:
            with isolation.scope(tenant_id, team_id):
                async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                    await c.execute(sa.insert(mcp_links).values(**row))
        except IntegrityError as e:
            raise Unprocessable(f"This team already has a link named {name}.", code="link_name_taken") from e
        return row

    async def delete(self, tenant_id: str, team_id: str, link_id: str) -> bool:
        """Removes the link; its address answers 404 from then on. Its calls stay in the call log with its id."""
        t = mcp_links
        with isolation.scope(tenant_id, team_id):
            q = sa.delete(t).where(t.c.tenant_id == tenant_id, team_visible(t), t.c.id == link_id)
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                return (await c.execute(q)).rowcount > 0

    async def set_paused(self, tenant_id: str, team_id: str, link_id: str, paused: bool) -> dict[str, Any] | None:
        t = mcp_links
        with isolation.scope(tenant_id, team_id):
            q = (
                sa.update(t)
                .where(t.c.tenant_id == tenant_id, team_visible(t), t.c.id == link_id)
                .values(paused=paused, updated_at=now_iso())
            )
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                await c.execute(q)
        return await self.get(tenant_id, team_id, link_id)
