"""MCP links: a named address for a chosen set of one team's tools and published workflows.

A link is a filter on the team's MCP door, never a second server: `/mcp/<team>/<slug>` lists only the link's tools and
refuses any other, and every call through it is one gateway call logged with the link's id (gateway_calls.link_id).
Who may connect and what a call may do stay the door's and the gateway's.
"""

from __future__ import annotations

from typing import ClassVar, Literal

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError

from ops_service_kit.errors import Unprocessable
from ops_service_kit.http import Out
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.listing import ListParams
from ops_store import Guarantee, isolation
from ops_store.isolation import attempt
from ops_store.listing import LISTED, ListPage, list_page
from ops_store.rows import one
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.store import Store
from ops_store.team_scope import acting_team, team_visible

from .calls import gateway_calls
from .modules import metadata
from .tenancy import ROLE

# Why the links list reads past the acting team: a caller who may see channels in several teams (the dev caller, a
# service token for the whole tenant) reads them on one page, and the query names each of those teams itself.
LINK_TEAMS = "the MCP links list reads every team its caller may see channels in, each named in the query"

mcp_links = sa.Table(
    "mcp_links",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    # Filtered and counted by the links list (`teamId`); uq_mcp_links_team_slug leads with it after the tenant.
    sa.Column("team_id", sa.String(64), nullable=False, info=LISTED),
    # The last part of the link's address; unique in its team, so one address names one link.
    sa.Column("slug", sa.String(64), nullable=False),
    sa.Column("name", sa.String(120), nullable=False),
    # Always "test" while outside assistants reach test data only; production is turned on per install later.
    sa.Column("environment", sa.String(16), nullable=False),
    # The picked tools: [{"name": <tool or workflow__<id>>, "kind": "tool" | "workflow", "title", "access"}].
    sa.Column("tools", sa.JSON, nullable=False),
    sa.Column("paused", sa.Boolean, nullable=False),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False, info=LISTED),
    sa.Column("updated_at", sa.String(32), nullable=False),
    sa.UniqueConstraint("tenant_id", "team_id", "slug", name="uq_mcp_links_team_slug"),
    # The links list sorts by creation time.
    sa.Index("ix_mcp_links_created_at", "tenant_id", "team_id", "created_at"),
    # Held to its team by the database (tools_0079): only a transaction run as ROLE in the link's team sees it.
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


class LinkedTool(Out):
    """One picked tool or workflow as the link stores it."""

    name: str
    title: str
    kind: Literal["tool", "workflow"]
    access: Literal["read", "write", "workflow"]
    # A picked workflow's description and input schema, as agents-service's catalog described it when the link was made.
    description: str | None = None
    input_schema: dict[str, JsonValue] | None = None


class McpLink(Out):
    id: str
    tenant_id: str
    team_id: str
    slug: str
    name: str
    environment: str
    tools: list[LinkedTool]
    paused: bool
    created_by: str
    created_at: str
    updated_at: str


class McpLinkRow(McpLink):
    """A link with its newest call (all null before its first), for the links list's Last call column."""

    last_at: str | None
    last_outcome: str | None
    last_client_name: str | None
    last_client_id: str | None


def _with_last_call(tenant_id: str, team_ids: list[str]) -> sa.Select[tuple[object, ...]]:
    """The teams' links, each joined to its newest call in its own team: one row a link, since calls made in the same
    instant are ranked by id too."""
    g, t = gateway_calls.c, mcp_links
    newest = (
        sa.select(
            g.team_id,
            g.link_id,
            g.created_at,
            g.outcome,
            g.client_name,
            g.client_id,
            sa.func.row_number().over(partition_by=g.link_id, order_by=(g.created_at.desc(), g.id.desc())).label("nth"),
        )
        .where(g.tenant_id == tenant_id, g.team_id.in_(team_ids), g.link_id.is_not(None))
        .subquery("last_call")
    )
    joined = t.outerjoin(
        newest, sa.and_(newest.c.link_id == t.c.id, newest.c.team_id == t.c.team_id, newest.c.nth == 1)
    )
    return (
        sa.select(
            *t.c,
            newest.c.created_at.label("last_at"),
            newest.c.outcome.label("last_outcome"),
            newest.c.client_name.label("last_client_name"),
            newest.c.client_id.label("last_client_id"),
        )
        .select_from(joined)
        .where(t.c.tenant_id == tenant_id, t.c.team_id.in_(team_ids), team_visible(t))
    )


class McpLinks(Store):
    # A slug is unique per team by constraint, so two creates of the same name cannot both win.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})
    role = ROLE

    async def listed(self, tenant_id: str, team_ids: list[str], params: ListParams) -> ListPage:
        """One page of the teams' links by name, ignoring case, each with its newest call (`McpLinkRow`); `teamId`
        (repeatable) narrows to some of `team_ids` and is counted in `facets`. The acting team alone reads in its own
        scope; several teams read tenant-wide, held to `team_ids` by the query, so a `teamId` outside them answers
        none."""
        own = team_ids == [acting_team()]
        held = (
            isolation.scope(tenant_id, team_ids[0]) if own else isolation.tenant_wide(LINK_TEAMS, tenant_id=tenant_id)
        )
        by_name = sa.func.lower(mcp_links.c.name)
        with held:
            async with self.tx() as c:
                return await list_page(
                    c,
                    _with_last_call(tenant_id, team_ids),
                    params,
                    search=[mcp_links.c.name],
                    sortable={"name": by_name, "createdAt": mcp_links.c.created_at},
                    default_sort=by_name,
                    filters={"teamId": mcp_links.c.team_id},
                    facets={"teamId": mcp_links.c.team_id},
                )

    async def one(self, tenant_id: str, team_id: str, link_id: str) -> McpLinkRow | None:
        """The team's link with its newest call."""
        with isolation.scope(tenant_id, team_id):
            q = _with_last_call(tenant_id, [team_id]).where(mcp_links.c.id == link_id)
            async with self.tx() as c:
                return await one(c, q, McpLinkRow)

    async def by_slug(self, tenant_id: str, team_id: str, slug: str) -> McpLink | None:
        t = mcp_links
        with isolation.scope(tenant_id, team_id):
            q = sa.select(t).where(
                t.c.tenant_id == tenant_id, team_visible(t), t.c.team_id == team_id, t.c.slug == slug
            )
            async with self.tx() as c:
                return await one(c, q, McpLink)

    async def create(
        self, tenant_id: str, team_id: str, *, slug: str, name: str, tools: list[LinkedTool], by: str
    ) -> McpLink:
        at = now_iso()
        link = McpLink(
            id=new_id("mcl"),
            tenant_id=tenant_id,
            team_id=team_id,
            slug=slug,
            name=name,
            environment="test",
            tools=tools,
            paused=False,
            created_by=by,
            created_at=at,
            updated_at=at,
        )
        # Each tool is stored with only the keys it has: a picked tool has no schema of its own.
        tools_json = [x.model_dump(exclude_none=True) for x in tools]
        with isolation.scope(tenant_id, team_id):
            async with self.tx() as c:
                try:
                    async with attempt(c):
                        await c.execute(
                            sa.insert(mcp_links).values(**link.model_dump(exclude={"tools"}), tools=tools_json)
                        )
                except IntegrityError as e:
                    raise Unprocessable(f"This team already has a link named {name}.", code="link_name_taken") from e
        return link

    async def delete(self, tenant_id: str, team_id: str, link_id: str) -> bool:
        """Removes the link; its address answers 404 from then on. Its calls stay in the call log with its id."""
        t = mcp_links
        with isolation.scope(tenant_id, team_id):
            q = sa.delete(t).where(t.c.tenant_id == tenant_id, team_visible(t), t.c.id == link_id)
            async with self.tx() as c:
                return (await c.execute(q)).rowcount > 0

    async def set_paused(self, tenant_id: str, team_id: str, link_id: str, paused: bool) -> bool:
        """False when the team has no such link."""
        t = mcp_links
        with isolation.scope(tenant_id, team_id):
            q = (
                sa.update(t)
                .where(t.c.tenant_id == tenant_id, team_visible(t), t.c.id == link_id)
                .values(paused=paused, updated_at=now_iso())
            )
            async with self.tx() as c:
                return (await c.execute(q)).rowcount > 0
