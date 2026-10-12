"""E1 failure modes: a paused thread resuming on a newer graph than it started on, a new thread not getting the
latest version, migrate moving a thread onto a graph without the node it waits in, migrate moving a thread that is not
waiting, and the same definition compiling again on every run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from ops_agent_kernel.ports import KernelPorts
from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.knowledge import KeywordPassageStore
from ops_agents.activities.tools import LocalReplySender, LocalToolExecutor
from ops_agents.graphs.common import GraphDeps
from ops_agents.graphs.definition import CompiledCache, WorkflowDefinition
from tests.api.test_graphs import run
from tests.conftest import SEED, FakeGraphModels, decide, last_run, scripted_model

FIXTURES = Path(__file__).parents[1] / "fixtures"
EMAIL: dict[str, Any] = json.loads((FIXTURES / "seed" / "dispute_emails.json").read_text())[1]


def definition(version: int) -> dict[str, Any]:
    if version == 1:
        return json.loads((FIXTURES / "seed" / "workflows.json").read_text())[0]
    return json.loads((FIXTURES / "workflows" / f"dispute_email.v{version}.json").read_text())


async def publish(client: AsyncClient, version: int) -> int:
    res = await client.post("/v1/graphs/dispute_email/versions", json={"definition": definition(version)})
    assert res.status_code == 201, res.text
    return res.json()["data"]["version"]


async def paused_thread(client: AsyncClient) -> str:
    res = await client.post("/v1/threads", json={"graph": "dispute_email"})
    assert res.status_code == 201, res.text
    tid = res.json()["data"]["threadId"]
    events = await run(client, tid, {"input": {"email": EMAIL}})
    assert events[-1]["data"]["status"] == "interrupted"
    return tid


async def state(client: AsyncClient, tid: str) -> dict[str, Any]:
    return (await client.get(f"/v1/threads/{tid}/state")).json()["data"]


async def test_paused_thread_finishes_on_its_pinned_version(client: AsyncClient) -> None:
    tid = await paused_thread(client)
    assert await publish(client, 2) == 2
    await decide(client, tid)
    assert (await last_run(client, tid))["status"] == "done"
    s = await state(client, tid)
    assert s["version"] == 1
    visited: list[str] = s["values"]["visited"]
    assert all(v.endswith("@v1") for v in visited), visited
    assert {"grade@v1", "human@v1", "send_reply@v1"} <= set(visited)
    assert s["values"]["status"] == "replied"


async def test_new_thread_runs_the_latest_version(client: AsyncClient) -> None:
    await publish(client, 2)
    tid = await paused_thread(client)
    s = await state(client, tid)
    assert s["version"] == 2
    assert {"compliance_check@v2", "score@v2"} <= set(s["values"]["visited"])
    assert not any(v.startswith("grade") for v in s["values"]["visited"])


async def test_migrate_refused_when_target_lacks_the_waiting_node(client: AsyncClient) -> None:
    tid = await paused_thread(client)
    await publish(client, 2)
    await publish(client, 3)
    res = await client.post(f"/v1/threads/{tid}/migrate", json={"toVersion": 3})
    assert res.status_code == 409 and res.json()["error"]["code"] == "node_missing"
    assert (await state(client, tid))["version"] == 1


async def test_migrate_refused_when_not_waiting(client: AsyncClient) -> None:
    tid = await paused_thread(client)
    await decide(client, tid, "rejected", reason="Not a dispute")
    await publish(client, 2)
    res = await client.post(f"/v1/threads/{tid}/migrate", json={"toVersion": 2})
    assert res.status_code == 409 and res.json()["error"]["code"] == "not_waiting"


async def test_migrate_allowed_then_resume_runs_on_target(client: AsyncClient) -> None:
    tid = await paused_thread(client)
    await publish(client, 2)
    res = await client.post(f"/v1/threads/{tid}/migrate", json={"toVersion": 2})
    assert res.status_code == 200, res.text
    await decide(client, tid)
    assert (await last_run(client, tid))["nodes"][:2] == ["human", "decide"]
    s = await state(client, tid)
    assert s["version"] == 2 and s["values"]["status"] == "replied"
    assert {"grade@v1", "human@v2", "send_reply@v2"} <= set(s["values"]["visited"])


def test_same_definition_compiles_once() -> None:
    catalog = load_catalog(SEED)
    deps = GraphDeps(
        catalog,
        KernelPorts(scripted_model(), LocalToolExecutor(catalog), KeywordPassageStore(catalog)),
        FakeGraphModels(),
        LocalReplySender(),
        "m",
    )
    cache = CompiledCache(deps, None)
    v1 = WorkflowDefinition.model_validate(definition(1))
    first = cache.get(v1)
    assert cache.get(WorkflowDefinition.model_validate(definition(1))) is first
    cache.get(WorkflowDefinition.model_validate(definition(2)))
    assert cache.compiles == 2
