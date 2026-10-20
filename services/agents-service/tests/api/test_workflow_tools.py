"""Published workflows in the agent's tool directory (c-062 T003, T004), by failure mode: a published workflow an
agent could be granted missing from the directory, a granted workflow search_tools cannot find by its words, an
unpublished, paused or ungranted workflow offered or callable, and a refusal that does not say why."""

from __future__ import annotations

import json
from typing import Any

from httpx import AsyncClient

from ops_agent_kernel import search
from ops_agents.api.child_runs import ChildRuns
from ops_agents.api.deps import Runtime
from tests.api.test_child_runs import stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - the shared app fixture
from tests.conftest import sse_events


async def directory(client: AsyncClient) -> dict[str, dict[str, Any]]:
    r = await client.get("/v1/tools")
    assert r.status_code == 200, r.text
    return {t["id"]: t for t in r.json()["data"]}


async def pause(client: AsyncClient, workflow: str) -> None:
    r = await client.post(f"/v1/workflows/{workflow}/status", json={"status": "paused"})
    assert r.status_code == 200, r.text


async def turn(client: AsyncClient, agent: str, message: str) -> list[dict[str, Any]]:
    tid = (await client.post("/v1/threads", json={"graph": "agent_wrapper", "metadata": {}})).json()["data"]["threadId"]
    body: dict[str, Any] = {"input": {"agent_id": agent, "message": message, "kb_ids": []}}
    res = await client.post(f"/v1/threads/{tid}/runs/stream", json=body)
    assert res.status_code == 200, res.text
    return sse_events(res.text)


async def test_a_published_workflow_is_in_the_directory_and_a_paused_one_is_not(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, _ = stack
    listed = await directory(client)
    wf = listed["workflow:dispute_email"]
    assert (wf["access"], wf["server"], wf["requiresApproval"]) == ("workflow", "Workflows", False)
    assert set(wf["inputSchema"]["required"]) == {"sender", "subject", "body"}
    assert "workflow:never_published" not in listed
    await pause(client, "dispute_email")
    assert "workflow:dispute_email" not in await directory(client)


async def test_access_keeps_only_the_kinds_asked_for(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    # The tools page lists workflow tools only; the directory answers with those, not the whole list to filter.
    client, _ = stack
    r = await client.get("/v1/tools", params={"access": "workflow"})
    assert r.status_code == 200, r.text
    kinds = {t["access"] for t in r.json()["data"]}
    assert kinds == {"workflow"}, kinds
    every = {t["access"] for t in (await client.get("/v1/tools")).json()["data"]}
    assert every > kinds, every


async def test_search_tools_finds_a_granted_workflow_by_its_words(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, rt = stack
    (offer,) = await ChildRuns(rt).offers(["workflow:dispute_email"])
    found = search.search([offer], "dispute email")
    assert [f["name"] for f in found] == ["workflow__dispute_email"] and found[0]["inputSchema"]["required"]
    assert search.search([offer], "mortgage") == []
    # Through a turn: the agent's own search returns the workflow it holds, by name, to call next.
    events = await turn(client, "ag_dispute", 'call search_tools {"query": "dispute email"}')
    ends = [e["data"] for e in events if e["event"] == "tool_end" and e["data"]["tool"] == "search_tools"]
    assert ends and "workflow__dispute_email" in json.dumps(ends[0]["output"]), ends


async def test_an_agent_without_the_grant_neither_finds_nor_runs_it(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, rt = stack
    events = await turn(client, "ag_branch", 'call search_tools {"query": "dispute email"}')
    ends = [e["data"] for e in events if e["event"] == "tool_end" and e["data"]["tool"] == "search_tools"]
    assert ends and "workflow__dispute_email" not in json.dumps(ends[0]["output"]), ends
    assert rt.graph_store is not None
    assert await rt.graph_store.threads("dispute_email") == [], "no child started"


async def test_granting_an_unpublished_or_paused_workflow_is_refused_with_the_reason(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, _ = stack
    held: list[str] = (await client.get("/v1/agents/ag_dispute")).json()["data"]["toolIds"]
    never = await client.patch("/v1/agents/ag_branch", json={"toolIds": ["workflow:never_published"]})
    assert never.status_code == 400 and never.json()["error"]["code"] == "not_published", never.text
    await pause(client, "dispute_email")
    paused = await client.patch("/v1/agents/ag_branch", json={"toolIds": ["workflow:dispute_email"]})
    assert paused.status_code == 400 and paused.json()["error"]["code"] == "workflow_paused", paused.text
    assert "paused" in paused.json()["error"]["message"]
    # An agent that already holds it keeps the grant while the workflow is paused; it is just not offered.
    kept = await client.patch("/v1/agents/ag_dispute", json={"toolIds": held})
    assert kept.status_code == 200 and "workflow:dispute_email" in kept.json()["data"]["toolIds"], kept.text


async def test_a_workflow_paused_between_offer_and_call_is_refused_with_the_reason(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, rt = stack
    assert await ChildRuns(rt).offers(["workflow:dispute_email"]), "offered while live"
    await pause(client, "dispute_email")
    tid = (await client.post("/v1/threads", json={"graph": "agent_wrapper", "metadata": {}})).json()["data"]["threadId"]
    outcome = await ChildRuns(rt).run(
        workflow="dispute_email", arguments={}, key="k-paused", parent_thread_id=tid, parent_run_id=None
    )
    assert (outcome.ok, outcome.output["code"]) == (False, "workflow_paused"), outcome.output
    assert "paused" in outcome.output["error"]
    assert rt.graph_store is not None
    assert await rt.graph_store.threads("dispute_email") == []
