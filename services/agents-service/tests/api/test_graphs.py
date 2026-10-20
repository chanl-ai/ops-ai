"""The four calls, by failure mode: a repeated run id re-running the graph, a resume with nothing waiting, the
redraft loop never ending, a review sending twice or skipping attachments, and a pause lost on restart."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from tests.conftest import FakeGraphModels, decide, last_run, sse_events

EMAILS: list[dict[str, Any]] = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "seed" / "dispute_emails.json").read_text()
)


async def thread(client: AsyncClient, graph: str) -> str:
    res = await client.post("/v1/threads", json={"graph": graph, "metadata": {"test": True}})
    assert res.status_code == 201, res.text
    return res.json()["data"]["threadId"]


async def run(client: AsyncClient, tid: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    res = await client.post(f"/v1/threads/{tid}/runs/stream", json=body)
    assert res.status_code == 200, res.text
    return sse_events(res.text)


def nodes(events: list[dict[str, Any]]) -> list[str]:
    return [e["node"] for e in events if e["event"] == "node_start"]


async def test_repeated_run_id_replays_without_running_again(
    client: AsyncClient, graph_models: FakeGraphModels
) -> None:
    tid = await thread(client, "complex_workflow")
    first = await run(client, tid, {"runId": "run_fixed", "input": {"email": EMAILS[1]}})
    extracted = list(graph_models.extracted)
    again = await run(client, tid, {"runId": "run_fixed", "input": {"email": EMAILS[1]}})
    assert again == first
    assert graph_models.extracted == extracted


async def test_resume_with_nothing_waiting_is_409(client: AsyncClient) -> None:
    tid = await thread(client, "simple_workflow")
    res = await client.post(f"/v1/threads/{tid}/runs/stream", json={"resume": {"decision": "approved"}})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "run_not_waiting"


async def test_redraft_loop_stops_at_three_attempts(client: AsyncClient, graph_models: FakeGraphModels) -> None:
    graph_models.scores = [0.1]
    tid = await thread(client, "complex_workflow")
    events = await run(client, tid, {"input": {"email": EMAILS[1]}})
    assert nodes(events).count("draft") == 3 and nodes(events).count("grade") == 3
    state = (await client.get(f"/v1/threads/{tid}/state")).json()["data"]
    assert state["values"]["attempts"] == 3
    assert state["interrupt"]["payload"]["kind"] == "review"


async def test_review_fans_out_and_sends_once(client: AsyncClient, graph_models: FakeGraphModels) -> None:
    tid = await thread(client, "complex_workflow")
    events = await run(client, tid, {"input": {"email": EMAILS[0]}})
    assert nodes(events).count("extract") == 3
    assert events[-1]["data"]["status"] == "interrupted"
    # A review is decided only in Reviews: resuming it here would skip the requester, step-up and approver checks.
    bypass = await client.post(f"/v1/threads/{tid}/runs/stream", json={"resume": {"decision": "approved"}})
    assert bypass.status_code == 409 and bypass.json()["error"]["code"] == "resume_via_review"
    await decide(client, tid)
    assert (await last_run(client, tid))["nodes"].count("send_reply") == 1
    second = await client.post(f"/v1/threads/{tid}/runs/stream", json={"resume": {"decision": "approved"}})
    assert second.status_code == 409
    state = (await client.get(f"/v1/threads/{tid}/state")).json()["data"]
    assert state["values"]["status"] == "replied" and state["values"]["sent"].startswith("OUT-")
    assert state["next"] == []
