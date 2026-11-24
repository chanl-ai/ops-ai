"""Which of a team's agents and workflows use each tool, by failure mode: an agent that grants a tool is not
named, a workflow whose tool step calls it is not named (a v1 tool step, or a v2 workflow's tool node, draft or live),
a tool nothing uses is said to be used, and another team's agents are named."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import AsyncClient

from ops_agents.api.agent_registry import SEED_TEAM
from ops_agents.api.routers import tool_uses as tool_uses_routes
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


async def test_a_workflow_whose_step_reads_a_document_type_is_named_and_another_type_is_not(
    client: AsyncClient,
) -> None:
    """documents-service asks this before deleting a type, so a workflow that reads it is never left without it."""
    seeded: Any = json.loads((Path(__file__).parents[2] / "seed" / "engine_workflows.json").read_text())
    rows = cast(
        list[dict[str, Any]], seeded if isinstance(seeded, list) else seeded.get("workflows") or list(seeded.values())
    )
    defs = [cast(dict[str, Any], w.get("definition", w)) for w in rows]
    found = next(d for d in defs if d.get("id") == "levy_intake")
    intake = {k: v for k, v in found.items() if k != "teamId"}
    made = await client.post("/v1/workflows/definitions", json={"definition": intake}, headers={"X-Team-Id": SEED_TEAM})
    assert made.status_code in (200, 201), made.text
    r = await client.get(
        "/v1/document-type-uses", params={"types": "legal_notice,nothing_reads_this"}, headers={"X-Team-Id": SEED_TEAM}
    )
    assert r.status_code == 200, r.text
    found = r.json()["data"]
    assert {"kind": "workflow", "id": "levy_intake", "name": intake["name"]} in found["legal_notice"], found
    assert found["nothing_reads_this"] == []


def _files_service(team: str | None) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="files", audience="agents", tenant_id="local", scopes=["workflows:view"],
        team_id=team,
    )  # fmt: skip
    return {"Authorization": f"Bearer {token}"}


async def test_files_service_is_told_a_workflow_uses_a_watch_draft_then_live_and_a_person_is_refused(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Files refuses Stop watching on this answer, so a workflow whose trigger names the watch, draft or live, must be
    named to the service's token. The Files changed step type waits on the schedule clock, so the Request trigger
    stands in for it here."""
    monkeypatch.setattr(tool_uses_routes, "FILES_TRIGGER", "ops.trigger.request")
    d = basic()
    d["nodes"][0]["parameters"] = {"watch": "wat_invoices"}
    made = await client.post("/v1/workflows/definitions", json={"definition": d}, headers={"X-Team-Id": SEED_TEAM})
    assert made.status_code in (200, 201), made.text
    params = {"watchIds": ["wat_invoices", "wat_unused"]}

    async def asked() -> Any:
        r = await client.get("/v1/watch-uses", params=params, headers=_files_service(SEED_TEAM))
        assert r.status_code == 200, r.text
        return r.json()["data"]

    named = {"workflowId": "refund_check", "name": d["name"]}
    assert await asked() == {"wat_invoices": [named | {"live": False}], "wat_unused": []}
    live = await client.post(
        "/v1/workflows/definitions/refund_check/publish-requests", json={}, headers={"X-Team-Id": SEED_TEAM}
    )
    assert live.status_code == 201, live.text
    assert await asked() == {"wat_invoices": [named | {"live": True}], "wat_unused": []}
    person = await client.get("/v1/watch-uses", params=params, headers={"X-Team-Id": SEED_TEAM})
    assert person.status_code == 403, person.text
