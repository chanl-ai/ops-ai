"""Which of a team's agents and workflows use each tool (c-609), by failure mode: an agent that grants a tool is not
named, a workflow whose tool step calls it is not named (a v1 tool step, or a v2 workflow's tool node, draft or live),
a tool nothing uses is said to be used, and another team's agents are named."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from ops_agents.api.agent_registry import SEED_TEAM
from ops_identity import dev_service_signer, mint_service_token
from tests.api.test_engine_definitions import basic

URL = "/v1/tool-uses"


def service(team: str | None) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="kb", audience="agents", tenant_id="local", scopes=["agents:view"],
        team_id=team,
    )  # fmt: skip
    return {"Authorization": f"Bearer {token}"}


async def uses(client: AsyncClient, tools: list[str], team: str | None = SEED_TEAM) -> dict[str, list[dict[str, Any]]]:
    # The console asks as a person in the team; a service naming no team reads nothing.
    headers = {"X-Team-Id": team} if team else service(None)
    r = await client.get(URL, params={"tools": ",".join(tools)}, headers=headers)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


async def test_an_agent_that_grants_a_tool_is_named_and_a_tool_nothing_uses_is_not(client: AsyncClient) -> None:
    agents: list[dict[str, Any]] = (await client.get("/v1/agents", params={"pageSize": 200})).json()["data"]["data"]
    granted = next(a for a in agents if a["toolIds"] and not a["toolIds"][0].startswith("workflow:"))
    tool = granted["toolIds"][0]
    found = await uses(client, [tool, "nothing_uses_this_tool"])
    assert {"kind": "agent", "id": granted["id"], "name": granted["name"]} in found[tool], found
    assert found["nothing_uses_this_tool"] == []


async def test_a_workflow_that_runs_an_agent_holding_the_tool_is_named(client: AsyncClient) -> None:
    """Wire hold review runs ag_fraud (the seed); a tool ag_fraud grants is used by that workflow too."""
    fraud = (await client.get("/v1/agents/ag_fraud")).json()["data"]
    tool = next(t for t in fraud["toolIds"] if not t.startswith("workflow:"))
    found = await uses(client, [tool])
    assert {"kind": "workflow", "id": "wire_hold_review", "name": "Wire hold review"} in found[tool], found


async def test_another_teams_agents_and_workflows_are_never_named(client: AsyncClient) -> None:
    agents: list[dict[str, Any]] = (await client.get("/v1/agents", params={"pageSize": 200})).json()["data"]["data"]
    tool = next(a for a in agents if a["toolIds"] and not a["toolIds"][0].startswith("workflow:"))["toolIds"][0]
    assert (await uses(client, [tool], team="team_nobody")) == {tool: []}
    assert (await uses(client, [tool], team=None)) == {tool: []}


async def test_a_workflow_whose_tool_node_calls_it_is_named_draft_or_live(client: AsyncClient) -> None:
    # A v2 workflow (the runner's) calls a tool from an ops.action.tool node: turning its app off stops it too.
    made = await client.post(
        "/v1/workflows/definitions", json={"definition": basic()}, headers={"X-Team-Id": SEED_TEAM}
    )
    assert made.status_code in (200, 201), made.text
    found = await uses(client, ["get_customer"])
    assert {"kind": "workflow", "id": "refund_check", "name": basic()["name"]} in found["get_customer"], found
