"""MCP links are held to their team by the database (tools_0079): another team, or another tenant, reading the links
table with SQL that names no team finds none of a team's links, which only the database policy can stop. Runs on the
compose PostgreSQL as `ops_tools_tenant`, the role every link store transaction runs as, since the database user the
tests connect as bypasses row security."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation
from ops_store.schema import isolation_kind
from ops_tools.store.mcp_links import LinkedTool, McpLinks, mcp_links
from ops_tools.store.tenancy import ROLE

TEAM_A, TEAM_B = "team_cards", "team_ops"


async def test_another_team_or_tenant_reads_no_link_without_the_team_clause(engine: AsyncEngine, tenant: str) -> None:
    assert isolation_kind(mcp_links) == "team"
    tools = [LinkedTool(name="lookup_case", title="Look up a case", kind="tool", access="read")]
    await McpLinks(engine).create(tenant, TEAM_A, slug="claims", name="Claims", tools=tools, by="t")
    count = sa.text("SELECT count(*) FROM mcp_links WHERE slug = 'claims'")
    for in_tenant, team, rows in ((tenant, TEAM_B, 0), ("t_elsewhere", TEAM_A, 0), (tenant, TEAM_A, 1)):
        with isolation.scope(in_tenant, team):
            async with isolation.isolated_tx(engine, role=ROLE) as c:
                seen = (await c.execute(count)).scalar_one()
        assert seen == rows, f"{in_tenant}/{team} read {seen} of team A's links"
