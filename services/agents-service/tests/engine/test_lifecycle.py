"""A v2 workflow version's lifecycle through the API, by failure mode: a draft that starts live runs, a publish that
skips the second person, a returned request that leaves the version stuck in review, a paused workflow that still
starts, an approval that unpauses it, a cancel a worker ignores or overwrites, a cancelled run still waiting in
Reviews, and a run whose result is not its End node's output."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.app import create_app
from ops_agents.api.engine_host import RunEvents, RunReviews, ThreadLeases
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.events import EventLog
from ops_agents.store.leases import Leases
from ops_agents.store.tenancy import LOCAL_TENANT, tenant_scope
from ops_engine import default_registry
from ops_engine.ports import Access, EnginePorts, ToolResult
from ops_engine.store import NotLiveError, RunStore
from ops_engine.worker import Worker, WorkerHost
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model

JAMES = {"X-Dev-User": "j.richardson@northfieldbank.com"}
MAYA = {"X-Dev-User": "m.okafor@northfieldbank.com"}


class NoTools:
    """This workflow calls no tool; a call would be a bug the test should see."""

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        raise AssertionError(f"unexpected tool call {operation}")

    async def access(self, operation: str) -> Access:
        return "read"

    async def mint(self, run_id: str, call: dict[str, Any], approval: dict[str, Any]) -> str | None:
        return None

    async def find(self, key: str, operation: str) -> ToolResult | None:
        return None


def definition(wid: str, outcome: str = "small") -> dict[str, Any]:
    """Amounts over 100 wait for a review; smaller ones end at once with the amount as the run's output."""

    def node(nid: str, kind: str, **params: Any) -> dict[str, Any]:
        return {"id": nid, "type": kind, "typeVersion": 1, "name": nid.capitalize(), "parameters": params}

    return {
        "schemaVersion": 2,
        "id": wid,
        "name": f"Refund {wid}",
        "nodes": [
            node("start", "ops.trigger.request"),
            node("fields", "ops.data.set", values={"amount": "$.input.amount"}),
            node("big", "ops.flow.if", conditions=[{"left": "$.nodes.fields.out.amount", "op": "gt", "right": 100}]),
            node("review", "ops.flow.humanReview", title="Refund over 100"),
            node("approved", "ops.flow.end", outcome="approved"),
            node("rejected", "ops.flow.end", outcome="rejected"),
            node("small", "ops.flow.end", outcome=outcome, output="$.nodes.fields.out.amount"),
        ],
        "connections": [
            {"from": {"node": a, "port": p}, "to": {"node": b, "port": "in"}}
            for a, p, b in (
                ("start", "payload", "fields"),
                ("fields", "out", "big"),
                ("big", "true", "review"),
                ("big", "false", "small"),
                ("review", "approve", "approved"),
                ("review", "reject", "rejected"),
            )
        ],
    }


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


@pytest.fixture
async def stack(engine: AsyncEngine) -> AsyncIterator[tuple[httpx.AsyncClient, Worker]]:
    # Publishing waits for a second person here: a workspace that switched requesterMayDecide off (c-186).
    settings = Settings(
        database_url=str(engine.url),
        seed_dir=SEED,
        registry_auto_approve=False,
        dev_policies={"requesterMayDecide": False},
    )
    app: FastAPI = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as c,
    ):
        yield c, worker(engine, NoTools())


def worker(engine: AsyncEngine, tools: Any, *, ttl: float = 6.0) -> Worker:
    owner = f"test-{uuid4().hex[:6]}"
    host = WorkerHost(
        tx=EngineTransactions(engine),
        registry=default_registry(),
        ports=EnginePorts(tools=tools, reviews=RunReviews()),
        leases=ThreadLeases(Leases(engine, owner=owner, ttl=ttl)),
        events=RunEvents(EventLog(engine)),
        checkpointer=InMemorySaver(),
        run_scope=tenant_scope,
        owner=owner,
    )
    return Worker(host)


def data(res: httpx.Response) -> Any:
    assert res.status_code < 300, res.text
    return res.json()["data"]


async def save(c: httpx.AsyncClient, d: dict[str, Any]) -> int:
    return int(data(await c.post("/v1/workflows/definitions", json={"definition": d}, headers=JAMES))["version"])


async def publish(c: httpx.AsyncClient, wid: str, version: int | None = None) -> dict[str, Any]:
    """James asks, Maya approves."""
    req = data(
        await c.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={"version": version}, headers=JAMES)
    )
    return data(await c.post(f"/v1/publish-requests/{req['id']}/decision", json={"decision": "approved"}, headers=MAYA))


async def start(c: httpx.AsyncClient, wid: str, amount: int, **extra: Any) -> httpx.Response:
    return await c.post("/v1/runs", json={"workflowId": wid, "input": {"amount": amount}, **extra}, headers=JAMES)


async def drain(w: Worker) -> None:
    while await w.work_once():
        pass


async def test_a_draft_starts_only_test_runs_until_a_second_person_approves_it(
    stack: tuple[httpx.AsyncClient, Worker],
) -> None:
    c, _ = stack
    wid = f"wf_{uuid4().hex[:8]}"
    assert await save(c, definition(wid)) == 1
    refused = await start(c, wid, 50)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "not_live", refused.text
    assert (await start(c, wid, 50, mode="test")).status_code == 202

    req = data(await c.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={}, headers=JAMES))
    assert req["status"] == "pending" and req["id"].startswith("WFP-")
    view = data(await c.get(f"/v1/workflows/definitions/{wid}", headers=JAMES))
    assert view["stage"] == "in_review" and view["liveVersion"] is None and view["review"]["id"] == req["id"]
    own = await c.post(f"/v1/publish-requests/{req['id']}/decision", json={"decision": "approved"}, headers=JAMES)
    assert own.status_code == 403
    assert (await start(c, wid, 50)).status_code == 409

    assert (
        data(await c.post(f"/v1/publish-requests/{req['id']}/decision", json={"decision": "approved"}, headers=MAYA))[
            "status"
        ]
        == "approved"
    )
    view = data(await c.get(f"/v1/workflows/definitions/{wid}", headers=JAMES))
    assert view["stage"] == "live" and view["liveVersion"] == 1
    assert data(await start(c, wid, 50))["version"] == 1

    # A newer save is a draft; live runs keep starting on v1 until it is approved, which supersedes v1.
    assert await save(c, definition(wid, outcome="small_v2")) == 2
    assert data(await start(c, wid, 50))["version"] == 1
    assert (await start(c, wid, 50, version=2)).json()["error"]["code"] == "not_live"
    await publish(c, wid, 2)
    view = data(await c.get(f"/v1/workflows/definitions/{wid}", headers=JAMES))
    assert [(v["version"], v["stage"]) for v in view["versions"]] == [(1, "superseded"), (2, "live")]
    assert data(await start(c, wid, 50))["version"] == 2


async def test_a_returned_request_leaves_the_version_a_draft(stack: tuple[httpx.AsyncClient, Worker]) -> None:
    c, _ = stack
    wid = f"wf_{uuid4().hex[:8]}"
    await save(c, definition(wid))
    req = data(await c.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={}, headers=JAMES))
    body = {"decision": "returned", "reason": "Name the outcome"}
    assert (
        data(await c.post(f"/v1/publish-requests/{req['id']}/decision", json=body, headers=MAYA))["status"]
        == "returned"
    )
    view = data(await c.get(f"/v1/workflows/definitions/{wid}", headers=JAMES))
    assert view["stage"] == "draft" and view["review"] is None and view["liveVersion"] is None
    assert (await start(c, wid, 50)).status_code == 409
    # A draft can be asked for again once the first request is closed.
    assert (
        await c.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={}, headers=JAMES)
    ).status_code == 201


async def test_a_paused_workflow_starts_no_live_run_and_stays_paused_across_an_approval(
    stack: tuple[httpx.AsyncClient, Worker],
) -> None:
    c, _ = stack
    wid = f"wf_{uuid4().hex[:8]}"
    early = await c.post(f"/v1/workflows/definitions/{wid}/pause", headers=JAMES)
    assert early.status_code == 404
    await save(c, definition(wid))
    assert (await c.post(f"/v1/workflows/definitions/{wid}/pause", headers=JAMES)).json()["error"]["code"] == "not_live"
    await publish(c, wid)
    assert data(await c.post(f"/v1/workflows/definitions/{wid}/pause", headers=JAMES))["paused"] is True
    refused = await start(c, wid, 50)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "workflow_paused"
    assert (await start(c, wid, 50, mode="test")).status_code == 202

    await save(c, definition(wid, outcome="small_v2"))
    await publish(c, wid, 2)
    view = data(await c.get(f"/v1/workflows/definitions/{wid}", headers=JAMES))
    assert view["paused"] is True and view["stage"] == "paused" and view["liveVersion"] == 2
    assert (await start(c, wid, 50)).status_code == 409

    assert data(await c.post(f"/v1/workflows/definitions/{wid}/resume", headers=JAMES))["paused"] is False
    assert data(await start(c, wid, 50))["version"] == 2


async def test_the_run_result_is_the_end_nodes_output(stack: tuple[httpx.AsyncClient, Worker]) -> None:
    c, w = stack
    wid = f"wf_{uuid4().hex[:8]}"
    await save(c, definition(wid))
    await publish(c, wid)
    run_id = data(await start(c, wid, 42))["runId"]
    assert data(await c.get(f"/v1/runs/{run_id}", headers=JAMES))["result"] is None
    await drain(w)
    run = data(await c.get(f"/v1/runs/{run_id}", headers=JAMES))
    assert run["status"] == "succeeded"
    assert run["result"] == {"node": "small", "name": "Small", "outcome": "small", "output": 42}


async def test_a_cancelled_run_never_starts_and_a_waiting_one_leaves_reviews(
    stack: tuple[httpx.AsyncClient, Worker],
) -> None:
    c, w = stack
    wid = f"wf_{uuid4().hex[:8]}"
    await save(c, definition(wid))
    await publish(c, wid)

    queued = data(await start(c, wid, 42))["runId"]
    cancelled = data(await c.post(f"/v1/runs/{queued}/cancel", headers=JAMES))
    assert cancelled["status"] == "cancelled" and cancelled["outcome"] == "by_user"
    assert data(await c.post(f"/v1/runs/{queued}/cancel", headers=JAMES))["status"] == "cancelled"
    await drain(w)
    run = data(await c.get(f"/v1/runs/{queued}", headers=JAMES))
    assert run["status"] == "cancelled" and run["steps"] == []

    waiting = data(await start(c, wid, 250))["runId"]
    await drain(w)
    assert data(await c.get(f"/v1/runs/{waiting}", headers=JAMES))["status"] == "waiting"
    # A waiting run's review is listed under its step id, run:node:iteration.
    review_id = f'"{waiting}:review:1"'
    assert review_id in (await c.get("/reviews", params={"pageSize": 500}, headers=MAYA)).text
    data(await c.post(f"/v1/runs/{waiting}/cancel", headers=JAMES))
    assert review_id not in (await c.get("/reviews", params={"pageSize": 500}, headers=MAYA)).text
    late = await c.post(f"/reviews/{waiting}/decision", json={"decision": "approved"}, headers=MAYA)
    assert late.status_code == 409, late.text
    await drain(w)
    assert data(await c.get(f"/v1/runs/{waiting}", headers=JAMES))["status"] == "cancelled"

    done = data(await start(c, wid, 42))["runId"]
    await drain(w)
    finished = await c.post(f"/v1/runs/{done}/cancel", headers=JAMES)
    assert finished.status_code == 409 and finished.json()["error"]["code"] == "run_finished"


async def test_a_pass_still_running_cannot_overwrite_a_cancel(
    engine: AsyncEngine, stack: tuple[httpx.AsyncClient, Worker]
) -> None:
    c, _ = stack
    wid = f"wf_{uuid4().hex[:8]}"
    await save(c, definition(wid))
    await publish(c, wid)
    run_id = data(await start(c, wid, 42))["runId"]
    data(await c.post(f"/v1/runs/{run_id}/cancel", headers=JAMES))
    runs = RunStore(EngineTransactions(engine))
    with tenant_scope(LOCAL_TENANT):
        await runs.update(run_id, status="succeeded", outcome="small")
        assert (await runs.get(run_id) or {})["status"] == "cancelled"


async def test_only_live_workflows_are_offered_as_options(stack: tuple[httpx.AsyncClient, Worker]) -> None:
    c, _ = stack
    draft, live = f"wf_{uuid4().hex[:8]}", f"wf_{uuid4().hex[:8]}"
    await save(c, definition(draft))
    await save(c, definition(live))
    await publish(c, live)
    offered = {
        o["value"]
        for o in data(await c.get("/v1/workflows/option-sources", params={"source": "workflows"}, headers=JAMES))
    }
    assert live in offered and draft not in offered
    agents = data(await c.get("/v1/workflows/option-sources", params={"source": "agents"}, headers=JAMES))
    assert agents and all(o["description"].startswith("Published v") for o in agents)
    assert (await c.get("/v1/workflows/option-sources", params={"source": "http"}, headers=JAMES)).status_code == 400


class SlowWrite:
    """A write that is under way until the test lets it answer."""

    def __init__(self) -> None:
        self.started, self.release, self.calls = asyncio.Event(), asyncio.Event(), 0

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return ToolResult(True, {"held": input.get("amount")})

    async def access(self, operation: str) -> Access:
        return "write"

    async def mint(self, run_id: str, call: dict[str, Any], approval: dict[str, Any]) -> str | None:
        return None

    async def find(self, key: str, operation: str) -> ToolResult | None:
        return None


def with_write(wid: str) -> dict[str, Any]:
    """Request, then a write to the bank, then the end."""
    return {
        "schemaVersion": 2,
        "id": wid,
        "name": f"Hold {wid}",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1},
            {
                "id": "hold",
                "type": "ops.action.tool",
                "typeVersion": 1,
                "parameters": {"operation": "place_hold", "input": {"amount": "$.input.amount"}},
            },
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1},
            {"id": "failed", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "failed"}},
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "hold", "port": "in"}},
            {"from": {"node": "hold", "port": "ok"}, "to": {"node": "done", "port": "in"}},
            {"from": {"node": "hold", "port": "refused"}, "to": {"node": "failed", "port": "in"}},
            {"from": {"node": "hold", "port": "error"}, "to": {"node": "failed", "port": "in"}},
        ],
    }


async def test_a_cancel_during_a_write_lets_the_write_finish_and_journals_it(
    engine: AsyncEngine, stack: tuple[httpx.AsyncClient, Worker]
) -> None:
    """The cancel dialog promises that a step already calling a system finishes that call. Cut off mid-call, the
    write's journal row would stay running on a run that is never reconciled: a write in doubt with no record."""
    c, _ = stack
    wid = f"wf_{uuid4().hex[:8]}"
    await save(c, with_write(wid))
    await publish(c, wid)
    run_id = data(await start(c, wid, 70))["runId"]
    tools = SlowWrite()
    # Heartbeats every 0.5 s, so several pass while the write is held.
    passing = asyncio.create_task(worker(engine, tools, ttl=1.5).work_once())
    await asyncio.wait_for(tools.started.wait(), 20)
    assert data(await c.post(f"/v1/runs/{run_id}/cancel", headers=JAMES))["status"] == "cancelled"
    await asyncio.sleep(1.6)
    tools.release.set()
    await asyncio.wait_for(passing, 20)

    run = data(await c.get(f"/v1/runs/{run_id}", headers=JAMES))
    steps = {s["nodeId"]: s for s in run["steps"]}
    assert run["status"] == "cancelled" and tools.calls == 1
    assert steps["hold"]["status"] == "ok" and steps["hold"]["output"] == {"held": 70}, steps.get("hold")
    assert "done" not in steps, "no step begins after the cancel"
    with tenant_scope(LOCAL_TENANT):
        assert {w["status"] for w in await RunStore(EngineTransactions(engine)).work(run_id)} == {"done"}


async def test_an_identity_field_read_from_the_run_is_refused_on_save(stack: tuple[httpx.AsyncClient, Worker]) -> None:
    """A `$.` operation would let run input choose what a reviewed workflow calls."""
    c, _ = stack
    d = with_write(f"wf_{uuid4().hex[:8]}")
    d["nodes"][1]["parameters"]["operation"] = "$.input.operation"
    refused = await c.post("/v1/workflows/definitions", json={"definition": d}, headers=JAMES)
    assert refused.status_code == 422, refused.text
    assert [k["node"] for k in refused.json()["error"]["details"]["checks"]] == ["hold"]


async def test_the_publish_review_names_what_each_step_acts_on(stack: tuple[httpx.AsyncClient, Worker]) -> None:
    c, _ = stack
    wid = f"wf_{uuid4().hex[:8]}"
    await save(c, with_write(wid))
    req = data(await c.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={}, headers=JAMES))
    assert "Step hold calls operation place_hold" in req["reasoning"], req["reasoning"]


async def test_a_start_after_a_pause_is_refused_by_the_store(
    engine: AsyncEngine, stack: tuple[httpx.AsyncClient, Worker]
) -> None:
    """The route reads the stage before it writes the run; the store reads it again under the version's lock, so a
    pause landing between the two cannot let a live run through."""
    c, _ = stack
    wid = f"wf_{uuid4().hex[:8]}"
    await save(c, definition(wid))
    await publish(c, wid)
    view = data(await c.post(f"/v1/workflows/definitions/{wid}/pause", headers=JAMES))
    run = {"id": f"wfrun_{uuid4().hex[:10]}", "team_id": "t", "workflow_id": wid, "version": 1}
    run |= {"digest": view["digest"], "mode": "live", "input": {}, "created_by": "a"}
    with tenant_scope(LOCAL_TENANT), pytest.raises(NotLiveError):
        await RunStore(EngineTransactions(engine)).create(run | {"run_key": run["id"]})
