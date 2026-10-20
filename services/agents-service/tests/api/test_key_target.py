"""An API key scoped to one agent or workflow (c-246), by failure mode: the key starts something other than its target,
by a run or a thread; a pinned key runs another version; a key's runs are recorded under its creator, so its traffic
cannot be counted and it cannot cancel what it started."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.store.graphs import GraphStore
from ops_agents.store.tenancy import tenant_scope
from tests.api.test_action_roles import live_run, refused, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, unowned_live

WF, PIN, AGENT = ({"X-API-Key": f"ok_ops.{k}", "X-Team-Id": "team_ops"} for k in ("wf", "pin", "agent"))
Stack = tuple[AsyncClient, AsyncEngine]


async def test_a_key_starts_its_target_only(stack: Stack) -> None:  # noqa: F811
    c, engine = stack
    for wid in ("refunds", "payouts"):
        await unowned_live(engine, wid, by="seed")
    other = await c.post("/v1/runs", json={**live_run(1), "workflowId": "payouts"}, headers=WF)
    agent_key = await c.post("/v1/runs", json=live_run(2), headers=AGENT)
    assert refused(other, "key_target") and refused(agent_key, "key_target"), (other.text, agent_key.text)
    thread: dict[str, Any] = {"graph": "complex_workflow", "metadata": {}}
    assert refused(await c.post("/v1/threads", json=thread, headers=WF), "key_target")
    mine = await c.post("/v1/runs", json=live_run(3), headers=WF)
    assert mine.status_code == 202, mine.text


async def test_a_pinned_key_runs_its_version_only(stack: Stack) -> None:  # noqa: F811
    c, engine = stack
    await unowned_live(engine, "refunds", by="seed")
    asked = await c.post("/v1/runs", json={**live_run(1), "version": 2}, headers=PIN)
    assert refused(asked, "key_target"), asked.text
    run = await c.post("/v1/runs", json=live_run(2), headers=PIN)
    assert run.status_code == 202 and run.json()["data"]["version"] == 1, run.text


async def test_a_keys_run_is_its_own(stack: Stack) -> None:  # noqa: F811
    c, engine = stack
    await unowned_live(engine, "refunds", by="seed")
    run_id = (await c.post("/v1/runs", json=live_run(1), headers=WF)).json()["data"]["runId"]
    detail = (await c.get(f"/v1/runs/{run_id}", headers=BUILDER)).json()["data"]
    assert (detail["startedBy"]["kind"], detail["startedBy"]["id"]) == ("key", "key_wf"), detail["startedBy"]
    assert (await c.post(f"/v1/runs/{run_id}/cancel", headers=WF)).status_code == 200


async def test_a_pinned_key_keeps_its_version_on_a_thread(stack: Stack) -> None:  # noqa: F811
    c, engine = stack
    with tenant_scope("acme"):
        for n in (1, 2):
            await GraphStore(engine).publish("refunds", {"name": "refunds", "n": n}, f"d{n}", "now")
    asked = await c.post("/v1/threads", json={"graph": "refunds", "version": 2, "metadata": {}}, headers=PIN)
    assert refused(asked, "key_target"), asked.text
    made = await c.post("/v1/threads", json={"graph": "refunds", "metadata": {}}, headers=PIN)
    assert made.status_code == 201 and made.json()["data"]["version"] == 1, made.text


async def test_a_scoped_key_reads_only_its_targets_runs_and_threads(stack: Stack) -> None:  # noqa: F811
    c, engine = stack
    for wid in ("refunds", "payouts"):
        await unowned_live(engine, wid, by="seed")
    mine = (await c.post("/v1/runs", json=live_run(1), headers=WF)).json()["data"]["runId"]
    theirs = await c.post("/v1/runs", json={**live_run(2), "workflowId": "payouts"}, headers=BUILDER)
    other_run = theirs.json()["data"]["runId"]
    listed = (await c.get("/v1/runs", headers=WF)).json()["data"]["data"]
    assert [r["id"] for r in listed] == [mine], listed
    assert (await c.get(f"/v1/runs/{other_run}", headers=WF)).status_code == 404
    thread = await c.post("/v1/threads", json={"graph": "complex_workflow", "metadata": {}}, headers=BUILDER)
    tid = thread.json()["data"]["threadId"]
    assert tid not in [t["threadId"] for t in (await c.get("/v1/threads", headers=WF)).json()["data"]]
    assert (await c.get(f"/v1/threads/{tid}/state", headers=WF)).status_code == 404
