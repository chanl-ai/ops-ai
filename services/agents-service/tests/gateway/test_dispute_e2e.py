"""The dispute workflow end to end with the tool gateway in the path: the reviewer's approval becomes a token bound
to the exact reply, the resumed send_reply carries it, and the gateway runs the send once."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.activities import gateway as gw
from ops_agents.api.app import create_app
from ops_agents.api.sweeper import recover
from ops_agents.store.graphs import metadata
from ops_agents.store.reviews import review_approvals
from ops_service_kit.settings import Settings
from tests.conftest import FakeGraphModels, decide, last_run, scripted_model, sse_events, step_up

from .conftest import SEED, Gateway

EMAILS: list[dict[str, Any]] = json.loads((Path(SEED) / "dispute_emails.json").read_text())


@pytest.fixture
async def apps(gateway: Gateway) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, review_key=SecretStr("test-review-key"))
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(review_approvals.metadata.create_all)
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        gateway=gateway.client,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as c,
    ):
        yield c, app


@pytest.fixture
def runtime(apps: tuple[httpx.AsyncClient, FastAPI]) -> httpx.AsyncClient:
    return apps[0]


async def run(client: httpx.AsyncClient, tid: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    res = await client.post(f"/v1/threads/{tid}/runs/stream", json=body)
    assert res.status_code == 200, res.text
    return sse_events(res.text)


async def new_thread(client: httpx.AsyncClient, graph: str) -> str:
    res = await client.post("/v1/threads", json={"graph": graph, "metadata": {}})
    return str(res.json()["data"]["threadId"])


async def paused_dispute(client: httpx.AsyncClient) -> tuple[str, dict[str, Any]]:
    tid = await new_thread(client, "complex_workflow")
    events = await run(client, tid, {"input": {"email": EMAILS[1]}})
    assert events[-1]["data"]["status"] == "interrupted"
    payload = (await client.get(f"/v1/threads/{tid}/state")).json()["data"]["interrupt"]["payload"]
    return tid, payload


def effects(rows: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return [(r["tool"], r["decision"], r["outcome"]) for r in rows]


async def test_dispute_sends_through_the_gateway(runtime: httpx.AsyncClient, gateway: Gateway) -> None:
    tid, payload = await paused_dispute(runtime)
    assert payload["call"]["tool"] == "send_reply"

    bare = await runtime.post(f"/v1/threads/{tid}/runs/stream", json={"resume": {"decision": "approved"}})
    assert bare.status_code == 409
    assert bare.json()["error"]["code"] == "resume_via_review"

    # Decide mints the approval token bound to the call and resumes with it in the decision.
    review = await decide(runtime, tid)
    assert review["status"] == "approved"
    assert (await last_run(runtime, tid))["status"] == "done"
    state = (await runtime.get(f"/v1/threads/{tid}/state")).json()["data"]
    assert state["values"]["status"] == "replied"
    rows = await gateway.log.for_thread(tid)
    assert effects(rows) == [("send_reply", "allow", "ok")]
    assert rows[0]["step"] == payload["call"]["step"]
    assert rows[0]["output"]["reference"] == state["values"]["sent"]


async def test_crash_after_the_gateway_sent_replays_instead_of_sending_again(
    apps: tuple[httpx.AsyncClient, FastAPI], gateway: Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The process dies after the gateway ran send_reply and before the node's checkpoint: the re-run node calls the
    gateway again with the same approved input, and gets the first send back."""
    runtime, app = apps
    tid, _ = await paused_dispute(runtime)

    real_send = gw.GatewayReplySender.send
    crashed: list[str] = []

    async def send_then_die(self: gw.GatewayReplySender, **kw: Any) -> str:
        reference = await real_send(self, **kw)
        if not crashed:
            crashed.append(reference)
            raise RuntimeError("process killed after the gateway accepted the send")
        return reference

    monkeypatch.setattr(gw.GatewayReplySender, "send", send_then_die)
    # The decision stands although its resume died; the sweeper, not a second decide, continues the run.
    assert (await decide(runtime, tid))["status"] == "approved"
    assert (await last_run(runtime, tid))["status"] == "error"

    # E2's sweeper continues a dead run from its last checkpoint: the send_reply node runs again from its start.
    runs = (await runtime.get(f"/v1/threads/{tid}/runs")).json()["data"]
    assert await recover(app.state.runtime, tid, runs[-1]["runId"]) is not None
    state = (await runtime.get(f"/v1/threads/{tid}/state")).json()["data"]
    assert state["values"]["sent"] == crashed[0]
    rows = await gateway.log.for_thread(tid)
    assert effects(rows) == [("send_reply", "allow", "ok"), ("send_reply", "allow", "replayed")]
    assert [r["effect"] for r in rows] == [True, False]


async def test_a_two_approver_write_needs_a_second_person(runtime: httpx.AsyncClient) -> None:
    tid = await new_thread(runtime, "agent_wrapper")
    message = "Place a 24-hour hold on wire W-88213, the payee was added this morning."
    events = await run(runtime, tid, {"input": {"agent_id": "ag_fraud", "message": message}})
    assert events[-1]["data"]["status"] == "interrupted", events[-3:]
    lee = "lee@northfieldbank.com"
    mine = await step_up(runtime)
    first = await runtime.post(f"/v1/threads/{tid}/approvals", json={"stepUpToken": mine})
    assert first.json()["data"]["approvalToken"] is None
    assert first.json()["data"]["needed"] == 2
    # Two approvers means two people: the first approver again is refused, not counted.
    same = await runtime.post(f"/v1/threads/{tid}/approvals", json={"stepUpToken": mine})
    assert same.status_code == 403, same.text
    # A step-up belongs to the person who made it: Lee cannot approve with James's.
    borrowed = await runtime.post(
        f"/v1/threads/{tid}/approvals", json={"stepUpToken": mine}, headers={"X-Dev-User": lee}
    )
    assert borrowed.status_code == 422 and "subject" in borrowed.json()["error"]["message"]
    second = await runtime.post(
        f"/v1/threads/{tid}/approvals", json={"stepUpToken": await step_up(runtime, lee)}, headers={"X-Dev-User": lee}
    )
    data = second.json()["data"]
    assert data["approvers"] == ["j.richardson@northfieldbank.com", "lee@northfieldbank.com"]
    assert data["approvalToken"]
