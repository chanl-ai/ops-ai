"""An agent's "used in" comes from the workflows that run it (c-068 T001), by failure mode: a v1 workflow whose
published version pins the agent missing or shown at the wrong version, a v2 workflow with an agent step missing, and
a workflow that does not use the agent listed against it, and the agent's own one-step workflow missing, so the
Settings tab says nothing reaches an agent that the Deployments tab says deploys through it (UX walk agents-2), or
counted as another workflow, so deleting warns about it and saving says to republish it."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient

ENGINE_SEED = Path(__file__).resolve().parents[2] / "seed" / "engine_workflows.json"


def summary_on(agent_id: str) -> dict[str, Any]:
    """The dev seed's v2 customer summary, with its agent step on `agent_id`."""
    d = copy.deepcopy(json.loads(ENGINE_SEED.read_text())[0])
    d["id"], d["name"] = "fraud_summary", "Fraud summary"
    for n in d["nodes"]:
        if n["type"] == "ops.ai.agent":
            n["parameters"]["agent"] = agent_id
    return d


async def agent(client: AsyncClient, agent_id: str) -> dict[str, Any]:
    r = await client.get(f"/v1/agents/{agent_id}")
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_used_in_lists_the_workflows_that_run_the_agent(client: AsyncClient) -> None:
    published = await client.post("/v1/workflows/definitions", json={"definition": summary_on("ag_fraud")})
    assert published.status_code == 201, published.text
    # A v2 workflow runs an agent once its version is live; dev auto-approve takes it live at once.
    assert (await client.post("/v1/workflows/definitions/fraud_summary/publish-requests", json={})).status_code == 201
    fraud = await agent(client, "ag_fraud")
    own = {
        "workflowId": "agent:ag_fraud",
        "workflowName": "Its own one-step workflow",
        "pinnedVersion": 7,
        "status": "live",
        "own": True,
    }
    assert fraud["usedIn"] == [
        {"workflowId": "fraud_summary", "workflowName": "Fraud summary", "pinnedVersion": 7, "status": "live"},
        own,
        {"workflowId": "wire_hold_review", "workflowName": "Wire hold review", "pinnedVersion": 7, "status": "live"},
    ], fraud["usedIn"]
    # Deleting the agent and republishing to adopt a version concern the other workflows only (UX walk agents-2).
    assert fraud["workflowIds"] == ["fraud_summary", "wire_hold_review"]
    listed = {a["id"]: a for a in (await client.get("/v1/agents?pageSize=50")).json()["data"]["data"]}
    assert listed["ag_fraud"]["usedIn"] == fraud["usedIn"]
    branch = await agent(client, "ag_branch")
    assert [u["workflowId"] for u in branch["usedIn"]] == ["agent:ag_branch"], "only its own workflow runs it"


async def test_settings_and_deployments_agree_on_where_an_agent_runs(client: AsyncClient) -> None:
    """Both tabs read the agent view: Deployments shows `wrapperWorkflowId`, Settings lists `usedIn`."""
    made = (await client.post("/v1/agents", json={"name": "Reach check", "role": "Answers"})).json()["data"]
    draft = await agent(client, made["id"])
    assert draft["usedIn"] == [] and draft.get("wrapperWorkflowId") is None, "an unpublished agent runs nowhere"
    published = await client.post(
        f"/v1/agents/{made['id']}/publish-requests", json={"version": made["version"], "note": "go"}
    )
    assert published.status_code in (200, 201), published.text
    live = await agent(client, made["id"])
    assert live["wrapperWorkflowId"] in [u["workflowId"] for u in live["usedIn"]], live["usedIn"]
