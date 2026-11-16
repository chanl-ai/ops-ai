"""`GET /v1/mcp-links` as a person, by failure mode: a link of another team (one they also belong to included, since a
person reads the team they act in) or of another tenant on their page; the team's links out of name order, ignoring
case."""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.mcp_links import LinkedTool, McpLinks

from . import test_egress_and_secrets_need_security_admin as security_admin
from .test_review_decisions import person

# The service as the security tests build it, with signed person tokens.
client = security_admin.client

TOOLS = [LinkedTool(name="lookup_case", title="Look up a case", kind="tool", access="read")]


async def _made(engine: AsyncEngine, tenant: str, team: str, name: str) -> None:
    await McpLinks(engine).create(tenant, team, slug=name.lower(), name=name, tools=TOOLS, by="seed")


async def test_the_list_holds_the_acting_teams_links_only_in_name_order(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    tenant: str,
) -> None:
    for team, name in (("team_cards", "billing"), ("team_cards", "Accounts"), ("team_cards", "Claims")):
        await _made(engine, tenant, team, name)
    await _made(engine, tenant, "team_ops", "Aardvark")
    await _made(engine, tenant, "team_payroll", "Bonus")
    await _made(engine, f"{tenant}_other", "team_cards", "Arrears")
    sam = person(tenant, "Sam Adeyemi", {"team_cards": "admin", "team_ops": "admin"})
    r = await client.get("/v1/mcp-links", headers=sam)
    assert r.status_code == 200, r.text
    listed = [(x["teamId"], x["name"]) for x in r.json()["data"]]
    assert listed == [("team_cards", "Accounts"), ("team_cards", "billing"), ("team_cards", "Claims")]
