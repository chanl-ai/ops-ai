"""`GET /v1/mcp-links` as a person, by failure mode: a link of another team (one they also belong to included, since a
person reads the team they act in) or of another tenant on their page; the team's links out of name order, ignoring
case; links of the same name repeated or lost between pages; and the store's read of several teams (the dev caller's
and a service token's) holding another team's links."""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.mcp_links import LinkedTool, McpLinks

from . import test_egress_and_secrets_need_security_admin as security_admin
from .test_review_decisions import person

# The service as the security tests build it, with signed person tokens.
client = security_admin.client

TOOLS = [LinkedTool(name="lookup_case", title="Look up a case", kind="tool", access="read")]


async def _made(engine: AsyncEngine, tenant: str, team: str, name: str, slug: str = "") -> str:
    made = await McpLinks(engine).create(tenant, team, slug=slug or name.lower(), name=name, tools=TOOLS, by="seed")
    return made.id


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
    page = r.json()["data"]
    listed = [(x["teamId"], x["name"]) for x in page["data"]]
    assert listed == [("team_cards", "Accounts"), ("team_cards", "billing"), ("team_cards", "Claims")]
    assert (page["pagination"]["total"], page["data"][0]["lastCall"]) == (3, None)
    # `teamId` narrows within the teams the caller reads and never widens them: Sam acts in team_cards, so team_ops
    # (where Sam is also an admin) and team_payroll answer no rows, and the facet counts only what was read.
    narrowed: dict[str, object] = {}
    for teams in (["team_cards"], ["team_ops"], ["team_payroll"], ["team_cards", "team_ops"]):
        r = await client.get("/v1/mcp-links", params={"teamId": teams}, headers=sam)
        assert r.status_code == 200, r.text
        got = r.json()["data"]
        narrowed[",".join(teams)] = (got["pagination"]["total"], got["facets"]["teamId"])
    assert narrowed == {
        "team_cards": (3, {"team_cards": 3}),
        "team_ops": (0, {"team_cards": 3}),
        "team_payroll": (0, {"team_cards": 3}),
        "team_cards,team_ops": (3, {"team_cards": 3}),
    }


async def test_links_of_one_name_each_appear_once_across_pages_and_past_the_end(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    tenant: str,
) -> None:
    ids = sorted([await _made(engine, tenant, "team_cards", n, f"s{i}") for i, n in enumerate(("Claims", "claims"))])
    sam = person(tenant, "Sam Adeyemi", {"team_cards": "admin"})
    seen: list[str] = []
    for page_no in (1, 2, 9):
        r = await client.get("/v1/mcp-links", params={"page": page_no, "pageSize": 1}, headers=sam)
        assert r.status_code == 200, r.text
        seen += [x["id"] for x in r.json()["data"]["data"]]
    assert seen == [*ids, ids[-1]], "a page past the end answers the last page"
