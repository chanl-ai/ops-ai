"""An agent step inside a workflow that asks for a gated write: before, the step ended with no text and nothing ran
or waited. Now the run stops at a review of that exact call, Reviews shows it, and decide resumes the agent."""

from __future__ import annotations

import json
from typing import Any

from httpx import AsyncClient

from tests.conftest import SEED, step_up

FRAUD: dict[str, Any] = next(a for a in json.loads((SEED / "chat_agents.json").read_text()) if a["id"] == "ag_fraud")
EMAIL = {"sender": "ops@harborpine.example", "subject": "Hold request", "body": "Place a 24-hour hold on wire W-88213"}


async def paused_on_agent_review(client: AsyncClient) -> str:
    definition = {
        "entry": "triage",
        "nodes": [
            {"id": "triage", "kind": "agent_turn", "config": {"agent": FRAUD}},
            {"id": "done", "kind": "end", "config": {"status": "handled"}},
        ],
        "edges": [{"source": "triage", "target": "done"}],
    }
    published = await client.post("/v1/graphs/agent_step_hold/versions", json={"definition": definition})
    assert published.status_code == 201, published.text
    tid = (await client.post("/v1/threads", json={"graph": "agent_step_hold", "metadata": {}})).json()["data"][
        "threadId"
    ]
    res = await client.post(f"/v1/threads/{tid}/runs/stream", json={"input": {"email": EMAIL}})
    assert res.status_code == 200, res.text
    return tid


async def test_a_gated_write_in_an_agent_step_waits_for_its_review(client: AsyncClient) -> None:
    tid = await paused_on_agent_review(client)
    state: dict[str, Any] = (await client.get(f"/v1/threads/{tid}/state")).json()["data"]
    interrupt: dict[str, Any] = state["interrupt"] or {}
    payload: dict[str, Any] = interrupt.get("payload") or {}
    assert payload.get("kind") == "approval" and payload["call"]["tool"] == "place_wire_hold"
    review = (await client.get(f"/reviews/{tid}")).json()["data"]
    assert review["actionTool"] == "place_wire_hold" and review["stepUp"] is True


async def test_deciding_it_resumes_the_agent_and_finishes_the_workflow(client: AsyncClient) -> None:
    tid = await paused_on_agent_review(client)
    res = await client.post(
        f"/reviews/{tid}/decision", json={"decision": "approved", "stepUpToken": await step_up(client)}
    )
    assert res.status_code == 200, res.text
    state = (await client.get(f"/v1/threads/{tid}/state")).json()["data"]
    assert state["interrupt"] is None
    assert state["values"]["status"] == "handled" and "hold is in place" in state["values"]["draft"]
