"""Which agents cite each knowledge base, for kb-service's "used by" (c-072 T007), by failure mode: a saved but
unpublished grant counted as live, a published grant missed, a token without `agents:view`, a team named in a query
instead of the token (c-168), and a person shown another team's agents by name (c-222)."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from ops_agents.api.agent_registry import SEED_TEAM
from ops_identity import dev_service_signer, mint_service_token

URL = "/v1/knowledge-usage"


def service(
    tenant: str | None = "local", team: str | None = None, scopes: tuple[str, ...] = ("agents:view",)
) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="kb", audience="agents", tenant_id=tenant, scopes=list(scopes), team_id=team
    )
    return {"Authorization": f"Bearer {token}"}


async def _usage(client: AsyncClient) -> dict[str, list[str]]:
    r = await client.get(URL, headers=service(team=SEED_TEAM))
    assert r.status_code == 200, r.text
    return {row["kbId"]: [a["id"] for a in row["agents"]] for row in r.json()["data"]}


async def test_a_base_lists_the_agents_whose_live_version_cites_it(client: AsyncClient) -> None:
    agents: list[dict[str, Any]] = (await client.get("/v1/agents", params={"pageSize": 200})).json()["data"]["data"]
    live = next(a for a in agents if a["publishedVersion"] and a["collections"])
    usage = await _usage(client)
    assert all(live["id"] in usage[kb] for kb in live["collections"]), (live["id"], live["collections"], usage)
    # A real base the live version does not cite: a save refuses an unknown value (c-141).
    extra = next(k for k in ("kb_lending", "kb_legal", "kb_support", "kb_people") if k not in live["collections"])
    saved = await client.patch(f"/v1/agents/{live['id']}", json={"collections": [*live["collections"], extra]})
    assert saved.status_code == 200, saved.text
    assert live["id"] not in (await _usage(client)).get(extra, []), "a saved, unpublished grant is not live"


async def test_agents_of_another_team_are_counted_not_named(client: AsyncClient) -> None:
    agents: list[dict[str, Any]] = (await client.get("/v1/agents", params={"pageSize": 200})).json()["data"]["data"]
    # Seeded agents belong to the seed team.
    live = next(a for a in agents if a["publishedVersion"] and a["collections"])
    kb = live["collections"][0]
    r = await client.get(URL, headers=service(team="team_nobody"))
    row = next(x for x in r.json()["data"] if x["kbId"] == kb)
    assert row["agents"] == [] and row["elsewhere"] >= 1, row
    mine = next(x for x in (await client.get(URL, headers=service(team=SEED_TEAM))).json()["data"] if x["kbId"] == kb)
    assert live["id"] in [a["id"] for a in mine["agents"]], mine


async def test_a_caller_naming_no_team_sees_counts_and_no_names(client: AsyncClient) -> None:
    """c-072 review: with no team every team's agents were named; it fails closed now, and a team in the query is
    not read (c-168)."""
    rows = (await client.get(URL, params={"teamId": SEED_TEAM}, headers=service())).json()["data"]
    assert rows and all(r["agents"] == [] and r["elsewhere"] >= 1 for r in rows), rows


async def test_a_person_reads_their_teams_usage_and_a_service_needs_its_scope(client: AsyncClient) -> None:
    """A person calls it too (c-222): their team's agents are named, another team's only counted."""
    agents: list[dict[str, Any]] = (await client.get("/v1/agents", params={"pageSize": 200})).json()["data"]["data"]
    live = next(a for a in agents if a["publishedVersion"] and a["collections"])
    kb = live["collections"][0]
    mine = next(x for x in (await client.get(URL, headers={"X-Team-Id": SEED_TEAM})).json()["data"] if x["kbId"] == kb)
    other = next(
        x for x in (await client.get(URL, headers={"X-Team-Id": "team_nobody"})).json()["data"] if x["kbId"] == kb
    )
    assert live["id"] in [a["id"] for a in mine["agents"]], mine
    assert other["agents"] == [] and other["elsewhere"] >= 1, other
    unscoped = await client.get(URL, headers=service(team=SEED_TEAM, scopes=()))
    assert unscoped.status_code == 403 and unscoped.json()["error"]["code"] == "scope_required", unscoped.text
