"""The execution-engine conformance suite (ADR execution-engine-seam, spec interpreter-and-nodes §9; ADR
fencing-and-timers), run against the LangGraph adapter on the scripted model.

Each test is named for the failure mode it guards. The stores are real: PostgreSQL for threads, runs, leases and
timers, the asyncpg checkpointer, and tools-service in-process deciding with OPA. A "restart" is a new app on the
same database. Two modes the LangGraph adapter does not provide yet are strict expected failures, so the day one
starts passing the suite says so.
"""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agents.activities import gateway as gw
from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.api.routing import route_thread
from ops_agents.api.runs import execute, resolve
from ops_agents.api.sweeper import recover
from ops_agents.api.timers import fire
from ops_agents.graphs.common import kernel_turn
from ops_agents.graphs.sla import review_loop
from ops_agents.store.leases import Leases
from ops_checkpointer import LeaseSupersededError
from ops_policy import input_hash
from ops_service_kit.ids import new_id
from ops_service_kit.settings import Settings
from tests.conftest import FakeGraphModels, fixture_knowledge, scripted, scripted_stream, sse_events
from tests.gateway.conftest import REVIEW_KEY, SEED, Gateway, engine, gateway, gateway_db_url

__all__ = ["engine", "gateway", "gateway_db_url"]  # pytest fixtures, used by name

EMAILS: list[dict[str, Any]] = json.loads((SEED / "dispute_emails.json").read_text())
WIRE = "Place a 24-hour hold on wire W-88213, the payee was added this morning."


@dataclass
class Counter:
    """The scripted model, counting the turns that reach it."""

    calls: int = 0

    def model(self) -> FunctionModel:
        def turn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            self.calls += 1
            return scripted(messages, info)

        async def stream(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
            self.calls += 1
            async for chunk in scripted_stream(messages, info):
                yield chunk

        return FunctionModel(turn, stream_function=stream)


@dataclass
class Adapter:
    """The agents service on the LangGraph adapter, with tools-service in the path."""

    gateway: Gateway
    model: Counter = field(default_factory=Counter)
    client: httpx.AsyncClient | None = None
    app: FastAPI | None = None

    @property
    def rt(self) -> Runtime:
        assert self.app is not None
        return self.app.state.runtime

    def process(self) -> AbstractAsyncContextManager[Adapter]:
        """One agents-service process; leaving it is a shutdown, entering another is a restart on the same data."""

        @asynccontextmanager
        async def running() -> AsyncGenerator[Adapter]:
            settings = Settings(
                seed_dir=SEED,
                review_key=SecretStr(REVIEW_KEY),
                timer_poll_seconds=0,
                sweep_interval_seconds=3600,
                lease_ttl_seconds=1.0,
            )
            app = create_app(
                settings,
                model=self.model.model(),
                graph_models=FakeGraphModels(),
                gateway=self.gateway.client,
                knowledge=fixture_knowledge(),
            )
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agents") as c,
            ):
                self.app, self.client = app, c
                yield self

        return running()

    @property
    def http(self) -> httpx.AsyncClient:
        assert self.client is not None
        return self.client

    async def thread(self, graph: str) -> str:
        return str(
            (await self.http.post("/v1/threads", json={"graph": graph, "metadata": {}})).json()["data"]["threadId"]
        )

    async def run(self, tid: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        res = await self.http.post(f"/v1/threads/{tid}/runs/stream", json=body)
        assert res.status_code == 200, res.text
        return sse_events(res.text)

    async def state(self, tid: str) -> dict[str, Any]:
        return (await self.http.get(f"/v1/threads/{tid}/state")).json()["data"]

    async def runs(self, tid: str) -> list[dict[str, Any]]:
        return (await self.http.get(f"/v1/threads/{tid}/runs")).json()["data"]

    async def approve(self, tid: str, *, step_up: str | None = None, as_user: str | None = None) -> dict[str, Any]:
        headers = {"X-Dev-User": as_user} if as_user else {}
        body = {"stepUpToken": step_up} if step_up else {}
        r = await self.http.post(f"/v1/threads/{tid}/approvals", json=body, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()["data"]

    async def decide(
        self, tid: str, decision: str = "approved", *, step_up: str | None = None, as_user: str | None = None
    ) -> dict[str, Any]:
        """The only way a review-owned step is decided: records the decision, mints the approval token once enough
        people approved, then resumes the thread with it."""
        headers = {"X-Dev-User": as_user} if as_user else {}
        body: dict[str, Any] = {"decision": decision} | ({"stepUpToken": step_up} if step_up else {})
        r = await self.http.post(f"/reviews/{tid}/decision", json=body, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()["data"]

    async def last_run(self, tid: str) -> dict[str, Any]:
        return (await self.runs(tid))[-1]

    async def step_up(self, as_user: str | None = None) -> str:
        """A signed step-up token for the caller, as the console's "Confirm it is you" gets one."""
        headers = {"X-Dev-User": as_user} if as_user else {}
        r = await self.http.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=headers)
        assert r.status_code == 200, r.text
        return str(r.json()["data"]["token"])

    async def effects(self, tid: str) -> list[tuple[str, str, str]]:
        return [
            (r["tool"], r["decision"], r["outcome"]) for r in await self.gateway.log.for_thread(tid, tenant_id="local")
        ]

    async def publish(self, name: str, **human: Any) -> httpx.Response:
        definition = {
            "entry": "human",
            "nodes": [
                {"id": "human", "kind": "human", "config": {"group": "tier1", **human}},
                {
                    "id": "decide",
                    "kind": "condition",
                    "config": {"rule": "decision", "approved": "done", "rejected": "close"},
                },
                {"id": "done", "kind": "end", "config": {"status": "replied"}},
                {"id": "close", "kind": "end", "config": {"status": "closed"}},
            ],
            "edges": [{"source": "human", "target": "decide"}],
        }
        return await self.http.post(f"/v1/graphs/{name}/versions", json={"definition": definition})

    async def waiting_review(self, name: str, **human: Any) -> str:
        assert (await self.publish(name, **human)).status_code == 201
        tid = await self.thread(name)
        assert (await self.run(tid, {"input": {"email": EMAILS[0]}}))[-1]["data"]["status"] == "interrupted"
        return tid

    async def breach(self, tid: str) -> str:
        return next(t["timerId"] for t in (await self.state(tid))["sla"]["timers"] if t["kind"] == "breach")


@pytest.fixture
async def adapter(gateway: Gateway) -> AsyncIterator[Adapter]:
    a = Adapter(gateway)
    async with a.process():
        yield a


async def paused_dispute(a: Adapter) -> tuple[str, dict[str, Any]]:
    tid = await a.thread("complex_workflow")
    assert (await a.run(tid, {"input": {"email": EMAILS[1]}}))[-1]["data"]["status"] == "interrupted"
    return tid, (await a.state(tid))["interrupt"]["payload"]


# 2. Worker crash mid-write double-posts.
async def test_crash_after_the_gateway_accepted_a_write_does_not_post_twice(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    tid, _ = await paused_dispute(adapter)
    real = gw.GatewayReplySender.send
    sent: list[str] = []

    async def send_then_die(self: gw.GatewayReplySender, **kw: Any) -> str:
        reference = await real(self, **kw)
        sent.append(reference)
        if len(sent) == 1:
            raise RuntimeError("worker killed after the gateway accepted the send")
        return reference

    monkeypatch.setattr(gw.GatewayReplySender, "send", send_then_die)
    assert (await adapter.decide(tid))["status"] == "approved"
    assert (await adapter.last_run(tid))["status"] == "error"
    assert await recover(adapter.rt, tid, (await adapter.runs(tid))[-1]["runId"]) is not None
    assert (await adapter.state(tid))["values"]["sent"] == sent[0] == sent[1]
    assert await adapter.effects(tid) == [("send_reply", "allow", "ok"), ("send_reply", "allow", "replayed")]


# 3. Duplicate trigger starts two runs.
async def test_the_same_run_key_twice_starts_one_run(adapter: Adapter) -> None:
    tid = await adapter.thread("complex_workflow")
    body = {"runId": f"run_{tid[4:]}", "input": {"email": EMAILS[0]}}
    first = await adapter.run(tid, body)
    again = await adapter.run(tid, body)
    assert again == first
    assert [r["kind"] for r in await adapter.runs(tid)] == ["input"]


# 4. Stale decision executes a superseded payload.
async def test_an_edit_after_approval_voids_the_old_token(adapter: Adapter) -> None:
    tid, payload = await paused_dispute(adapter)
    token = (await adapter.approve(tid))["approvalToken"]
    # An edit is a write like any other: it holds the thread's lease and carries its generation.
    leases = adapter.rt.leases
    assert leases is not None
    # Updating the state moves the thread back before its review, so the edit run carries it to the review again,
    # now showing the edited reply.
    run_id = new_id("run")
    generation = await leases.acquire(tid, run_id)
    row, graph = await resolve(adapter.rt, tid)
    await graph.aupdate_state(
        {"configurable": {"thread_id": tid, "lease_generation": generation}},
        {"draft": payload["draft"] + " Edited after approval."},
        as_node="grade",
    )
    store = adapter.rt.graph_store
    assert store is not None
    assert await store.start_run(run_id, tid, "input", "2026-10-10T00:00:00Z", {"edit": True}, generation=generation)
    edited = [e async for e in execute(adapter.rt, row, graph, graph_input=None, run_id=run_id, kind="input")]
    assert edited[-1]["data"]["status"] == "interrupted", edited[-2:]
    # The token minted before the edit cannot be used: a review is resumed only by decide, which mints from the
    # input the thread is waiting on now.
    stale = await adapter.http.post(
        f"/v1/threads/{tid}/runs/stream", json={"resume": {"decision": "approved", "approvalToken": token}}
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "resume_via_review"
    edited_call = (await adapter.state(tid))["interrupt"]["payload"]["call"]
    assert (await adapter.decide(tid))["status"] == "approved"
    rows = await adapter.gateway.log.for_thread(tid, tenant_id="local")
    assert [(r["tool"], r["decision"], r["outcome"]) for r in rows] == [("send_reply", "allow", "ok")]
    assert rows[0]["input_hash"] == input_hash(edited_call["input"])


# 7. SLA timeout approves.
async def test_no_timeout_path_approves(adapter: Adapter) -> None:
    refused = await adapter.publish("conf_timeout_approve", sla="1s", onTimeout="approve")
    assert refused.status_code == 400
    tid = await adapter.waiting_review("conf_timeout_reject", sla="1s", onTimeout="reject")
    await asyncio.sleep(1.1)
    assert (await fire(adapter.rt, tid, await adapter.breach(tid))).status == "fired"
    values = (await adapter.state(tid))["values"]
    assert values["status"] == "closed"
    assert values["decision"]["decision"] == "rejected"


# 8. Customer reply does not pause the SLA.
async def test_a_customer_reply_restarts_the_sla(adapter: Adapter) -> None:
    tid = await adapter.waiting_review("conf_reply", sla="2s", onTimeout="reject")
    before = await adapter.breach(tid)
    await asyncio.sleep(1.5)
    assert (await adapter.http.post(f"/v1/threads/{tid}/events", json={"type": "customer_reply"})).status_code == 200
    await asyncio.sleep(0.7)
    assert (await fire(adapter.rt, tid, before)).status == "cancelled"
    timers = (await adapter.state(tid))["sla"]["timers"]
    after = next(t["timerId"] for t in timers if t["kind"] == "breach" and t["state"] == "open")
    assert (await fire(adapter.rt, tid, after)).status == "not_due"


# 9. Retry budget exhausted ends silently.
async def test_an_exhausted_retry_budget_lands_in_manual_handling_with_the_error(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    tid = await adapter.waiting_review("conf_retry", sla="1s", onTimeout="reject")
    timer_id = await adapter.breach(tid)
    await asyncio.sleep(1.1)

    def failing(payload: dict[str, Any], settings: Any, raise_interrupt: Callable[[dict[str, Any]], Any]) -> Any:
        def ask(p: dict[str, Any]) -> Any:
            decision = raise_interrupt(p)
            if decision.get("decision") == "timeout":
                raise RuntimeError("case service unavailable")
            return decision

        return review_loop(payload, settings, ask)

    # The human node looks `review_loop` up when it runs, so replacing it reaches the compiled graph.
    monkeypatch.setattr("ops_agents.graphs.definition.review_loop", failing)
    # The budget is the ADR's three attempts, written here rather than read from the code under test.
    statuses = [(await fire(adapter.rt, tid, timer_id)).status for _ in range(4)]
    assert statuses == ["retry", "retry", "retry", "failed"]
    failed = [e for e in (await adapter.state(tid))["sla"]["events"] if e["event"] == "sla.fire_failed"]
    assert failed and "case service unavailable" in str(failed[0]["data"]["error"])


async def wire_waiting(a: Adapter) -> str:
    tid = await a.thread("agent_wrapper")
    assert (await a.run(tid, {"input": {"agent_id": "ag_fraud", "message": WIRE}}))[-1]["data"][
        "status"
    ] == "interrupted"
    return tid


SECOND = "lee@harborpine.example"


async def first_approval(a: Adapter, tid: str) -> None:
    """The first of a money step's two approvers; the thread stays paused for the second."""
    assert (await a.decide(tid, step_up=await a.step_up()))["status"] == "in_review"


async def second_approval(a: Adapter, tid: str) -> dict[str, Any]:
    return await a.decide(tid, step_up=await a.step_up(SECOND), as_user=SECOND)


# 12. Kernel interrupt lost across a wait.
async def test_an_agent_interrupt_survives_a_restart_and_resumes_the_same_call(gateway: Gateway) -> None:
    a = Adapter(gateway)
    async with a.process():
        tid = await wire_waiting(a)
        pending_key = (await a.state(tid))["interrupt"]["payload"]["call"]["step"]
        await first_approval(a, tid)
    async with a.process():  # a new process on the same database and checkpointer
        before = a.model.calls
        await second_approval(a, tid)
        assert (await a.last_run(tid))["status"] == "done"
        rows = await a.gateway.log.for_thread(tid, tenant_id="local")
        assert [(r["tool"], r["step"], r["outcome"]) for r in rows] == [("place_wire_hold", pending_key, "ok")]
        assert a.model.calls - before == 1  # only the closing answer; the approved call is not asked for again


# 12a. Agent activity retried after a crash repeats model or tool calls.
async def crash_after_the_resume_turn(adapter: Adapter, monkeypatch: pytest.MonkeyPatch) -> tuple[str, int]:
    """The worker dies after the resumed kernel turn has run the approved tool, before the node's checkpoint.
    E2's sweeper continues the thread, so the resume node runs again from its start."""
    tid = await wire_waiting(adapter)
    await first_approval(adapter, tid)
    crashed: list[str] = []

    async def turn_then_die(node: str, *args: Any, **kw: Any) -> Any:
        result = await kernel_turn(node, *args, **kw)
        if node == "resume" and not crashed:
            crashed.append(node)
            raise RuntimeError("worker killed after the resumed turn committed its tool call")
        return result

    monkeypatch.setattr("ops_agents.graphs.agent_wrapper.kernel_turn", turn_then_die)
    before = adapter.model.calls
    await second_approval(adapter, tid)
    assert (await adapter.last_run(tid))["status"] == "error"
    assert await recover(adapter.rt, tid, (await adapter.runs(tid))[-1]["runId"]) is not None
    return tid, adapter.model.calls - before


async def test_an_agent_retry_after_a_crash_repeats_no_tool_call(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    tid, _ = await crash_after_the_resume_turn(adapter, monkeypatch)
    assert [(t, o) for t, _, o in await adapter.effects(tid)] == [
        ("place_wire_hold", "ok"),
        ("place_wire_hold", "replayed"),
    ]


async def test_an_agent_retry_after_a_crash_repeats_no_model_call(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, model_calls = await crash_after_the_resume_turn(adapter, monkeypatch)
    assert model_calls == 1


# 13. R9 cancels an in-flight write.
async def paused_definition_dispute(a: Adapter) -> str:
    tid = await a.thread("dispute_email")
    assert (await a.run(tid, {"input": {"email": EMAILS[1]}}))[-1]["data"]["status"] == "interrupted"
    return tid


def route_skipped(runs: list[dict[str, Any]]) -> list[str]:
    return [
        n for r in runs for e in r.get("events", []) if e.get("event") == "route.skipped" for n in e["data"]["nodes"]
    ]


async def journal(a: Adapter, tid: str) -> list[dict[str, Any]]:
    store = a.rt.graph_store
    assert store is not None
    return await store.runs(tid)


async def test_routing_a_waiting_thread_to_people_raises_the_manual_step(adapter: Adapter) -> None:
    tid = await paused_definition_dispute(adapter)
    r = await adapter.http.post(f"/v1/threads/{tid}/route-to-people", json={"reason": "bad definition version"})
    assert r.status_code == 202 and r.json()["data"]["status"] == "routed"
    payload = (await adapter.state(tid))["interrupt"]["payload"]
    assert (payload["kind"], payload["reason"]) == ("manual", "bad definition version")
    skipped = route_skipped(await journal(adapter, tid))
    assert "send_reply" in skipped and "classify" not in skipped
    assert await adapter.effects(tid) == []


async def test_routing_to_people_lets_the_write_finish_and_skips_the_rest(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    tid = await paused_definition_dispute(adapter)
    real = gw.GatewayReplySender.send
    routed: list[str] = []

    async def send_while_routed(self: gw.GatewayReplySender, **kw: Any) -> str:
        # The publisher routes the thread while its reply is being sent: the write is in flight.
        routed.append(await route_thread(adapter.rt, tid, "bad definition version", "publisher@bank.test"))
        return await real(self, **kw)

    monkeypatch.setattr(gw.GatewayReplySender, "send", send_while_routed)
    await adapter.decide(tid)
    assert routed == ["pending"]
    assert (await adapter.last_run(tid))["status"] == "interrupted"
    assert await adapter.effects(tid) == [("send_reply", "allow", "ok")]
    skipped = route_skipped(await journal(adapter, tid))
    assert "done" in skipped and "send_reply" not in skipped
    assert (await adapter.state(tid))["interrupt"]["payload"]["kind"] == "manual"


# Fencing and timers: a paused worker cannot write after takeover.
async def test_a_paused_worker_cannot_write_after_takeover(adapter: Adapter) -> None:
    tid, _ = await paused_dispute(adapter)
    engine = adapter.rt.leases.engine  # type: ignore[union-attr]
    paused = await Leases(engine, owner="paused-worker", ttl=0.5).acquire(tid, "run_paused")
    await asyncio.sleep(0.7)  # the worker is paused past its lease (SIGSTOP)
    new = await Leases(engine, owner="new-owner", ttl=30).acquire(tid, "run_new")
    saver = adapter.rt.saver
    await saver.araise_fence(tid, new)
    snapshot = await saver.aget_tuple({"configurable": {"thread_id": tid, "checkpoint_ns": ""}})
    stale = {"configurable": {"thread_id": tid, "checkpoint_ns": "", "lease_generation": paused}}
    with pytest.raises(LeaseSupersededError):
        await saver.aput(stale, snapshot.checkpoint, snapshot.metadata, {})
    store = adapter.rt.graph_store
    assert store is not None
    with pytest.raises(LeaseSupersededError):
        await store.set_thread_status(tid, "busy", "2026-10-10T00:00:00Z", generation=paused)


# Fencing and timers: a timer due during a run fires once after it, or is cancelled if the run decided.
async def test_a_timer_due_during_a_run_fires_once_after_it_or_is_cancelled(adapter: Adapter) -> None:
    waits = await adapter.waiting_review("conf_due_waits", sla="1s", onTimeout="reject")
    decides = await adapter.waiting_review("conf_due_decides", sla="1s", onTimeout="reject")
    await asyncio.sleep(1.1)
    leases = adapter.rt.leases
    assert leases is not None
    for tid in (waits, decides):
        await leases.acquire(tid, "run_reviewer")
        assert (await fire(adapter.rt, tid, await adapter.breach(tid))).status == "busy"
        await leases.release(tid, "run_reviewer")
    await adapter.decide(decides)
    results = [(await fire(adapter.rt, waits, await adapter.breach(waits))).status for _ in range(2)]
    assert results == ["fired", "duplicate"]
    assert (await fire(adapter.rt, decides, await adapter.breach(decides))).status == "cancelled"
