"""A reviewed write in a v2 workflow goes through the gateway as a v1 one does (c-061 T017): the review decision mints
the token bound to the write's exact call, the tool node sends that call with it, and the gateway runs it. By failure
mode: a write sent with no decision behind it, a decision that mints no token or one for another input, and a
reviewer's edit that does not reach the call."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.activities.gateway import GatewayClient
from ops_agents.api.app import create_app
from ops_agents.api.engine_host import ApprovalMinter, GatewayTools, RunEvents, RunReviews, ThreadLeases
from ops_agents.api.worker import enter_run
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.events import EventLog
from ops_agents.store.leases import Leases
from ops_agents.store.tenancy import current_team, tenant_scope
from ops_engine import default_registry
from ops_engine.ports import EnginePorts
from ops_engine.store import RunStore
from ops_engine.worker import Worker, WorkerHost
from ops_identity import ServiceClient, dev_service_signer
from ops_service_kit.settings import Settings
from tests.conftest import FakeGraphModels, fixture_knowledge, scripted_model

from .conftest import REVIEW_KEY, SEED, Gateway

STARTER = {"X-Dev-User": "j.richardson@northfieldbank.com"}
REVIEWER = {"X-Dev-User": "m.okafor@northfieldbank.com"}


def definition(wid: str, *, reviewed: bool) -> dict[str, Any]:
    note: dict[str, Any] = {
        "id": "note",
        "type": "ops.action.tool",
        "typeVersion": 1,
        "parameters": {
            "operation": "add_customer_note",
            "input": {"customerId": "$.input.customerId", "text": "$.input.text"},
            **({"approvedBy": "review"} if reviewed else {}),
        },
    }
    ends = [
        {"id": e, "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": e}}
        for e in ("noted", "refused", "failed", "rejected")
    ]
    review = {
        "id": "review",
        "type": "ops.flow.humanReview",
        "typeVersion": 1,
        "parameters": {
            "title": "Write the note",
            "options": [
                {
                    "name": "write",
                    "call": {"node": "note"},
                    "inputs": [{"name": "text", "type": "string", "required": True}],
                },
                "reject",
            ],
        },
    }
    nodes = [{"id": "start", "type": "ops.trigger.request", "typeVersion": 1}, *([review] if reviewed else []), note]
    conns = [
        {"from": {"node": "note", "port": p}, "to": {"node": e, "port": "in"}}
        for p, e in (("ok", "noted"), ("refused", "refused"), ("error", "failed"))
    ]
    if reviewed:
        conns += [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "review", "port": "in"}},
            {"from": {"node": "review", "port": "write"}, "to": {"node": "note", "port": "in"}},
            {"from": {"node": "review", "port": "reject"}, "to": {"node": "rejected", "port": "in"}},
        ]
    else:
        conns.append({"from": {"node": "start", "port": "payload"}, "to": {"node": "note", "port": "in"}})
        ends = [e for e in ends if e["id"] != "rejected"]
    return {"schemaVersion": 2, "id": wid, "nodes": [*nodes, *ends], "connections": conns}


@pytest.fixture
async def stack(engine: AsyncEngine, gateway: Gateway) -> AsyncIterator[tuple[httpx.AsyncClient, Worker]]:
    # A workspace that switched requesterMayDecide off (c-186): the starter does not decide their own run.
    settings = Settings(
        database_url=str(engine.url),
        seed_dir=SEED,
        review_key=SecretStr(REVIEW_KEY),
        dev_policies={"requesterMayDecide": False},
    )
    app: FastAPI = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        gateway=gateway.client,
        knowledge=fixture_knowledge(),
    )
    owner = f"test-{uuid4().hex[:6]}"
    host = WorkerHost(
        tx=EngineTransactions(engine),
        registry=default_registry(),
        ports=EnginePorts(
            tools=GatewayTools(
                GatewayClient(
                    # The run's team rides in the token, as required_client sets it (app.py).
                    ServiceClient(
                        gateway.client,
                        dev_service_signer(),
                        "agents",
                        "tools",
                        tenant=lambda: "local",
                        team=current_team,
                    )
                ),
                ApprovalMinter(engine, REVIEW_KEY, 300),
            ),
            reviews=RunReviews(),
        ),
        leases=ThreadLeases(Leases(engine, owner=owner, ttl=6.0)),
        events=RunEvents(EventLog(engine)),
        checkpointer=InMemorySaver(),
        run_scope=tenant_scope,
        owner=owner,
        enter_run=enter_run,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as c,
    ):
        yield c, Worker(host)


async def start(client: httpx.AsyncClient, d: dict[str, Any], text: str) -> str:
    assert (await client.post("/v1/workflows/definitions", json={"definition": d})).status_code in (200, 201)
    # A saved version is a draft; dev auto-approve takes it live, as a reviewer's approval would.
    published = await client.post(f"/v1/workflows/definitions/{d['id']}/publish-requests", json={})
    assert published.status_code == 201, published.text
    body = {"workflowId": d["id"], "input": {"customerId": "CUS-1001", "text": text}}
    res = await client.post("/v1/runs", json=body, headers=STARTER)
    assert res.status_code == 202, res.text
    return str(res.json()["data"]["runId"])


async def finish(worker: Worker, client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    """Works the queue until this run stops; other tests' leftovers on the shared database are worked too."""
    for _ in range(50):
        if not await worker.work_once():
            break
    return (await client.get(f"/v1/runs/{run_id}")).json()["data"]


def note_step(run: dict[str, Any]) -> dict[str, Any]:
    return next(s for s in run["steps"] if s["nodeId"] == "note")


async def test_a_write_with_no_decision_behind_it_is_refused(
    stack: tuple[httpx.AsyncClient, Worker], gateway: Gateway
) -> None:
    client, worker = stack
    run_id = await start(client, definition(f"wf_{uuid4().hex[:8]}", reviewed=False), "x")
    run = await finish(worker, client, run_id)
    assert note_step(run)["port"] == "refused", note_step(run)
    assert run["outcome"] == "refused"
    logged = await gateway.log.for_thread(run_id, tenant_id="local")
    assert [(r["decision"], r["outcome"]) for r in logged] == [("deny", "refused")], logged


async def test_the_decision_mints_the_token_for_the_edited_call_and_the_write_runs(
    stack: tuple[httpx.AsyncClient, Worker], gateway: Gateway, engine: AsyncEngine
) -> None:
    client, worker = stack
    run_id = await start(client, definition(f"wf_{uuid4().hex[:8]}", reviewed=True), "draft text")
    waiting = await finish(worker, client, run_id)
    assert waiting["status"] == "waiting"
    option = next(o for o in waiting["waiting"]["payload"]["options"] if o["name"] == "write")
    assert option["call"]["step"] == f"{run_id}:note:1:1" and option["call"]["input"]["text"] == "draft text"
    bad = await client.post(
        f"/reviews/{run_id}/decision", json={"decision": "write", "inputs": {"amount": 5}}, headers=REVIEWER
    )
    assert bad.status_code == 400, "an input the option does not declare is refused"
    own = await client.post(f"/reviews/{run_id}/decision", json={"decision": "write"}, headers=STARTER)
    assert own.status_code == 403, "the starter cannot decide their own run"
    ok = await client.post(
        f"/reviews/{run_id}/decision", json={"decision": "write", "inputs": {"text": "Reviewed note"}}, headers=REVIEWER
    )
    assert ok.status_code == 200, ok.text
    done = await finish(worker, client, run_id)
    step = note_step(done)
    assert (done["outcome"], step["port"]) == ("noted", "ok"), step
    logged = await gateway.log.for_thread(run_id, tenant_id="local")
    assert [(r["decision"], r["outcome"]) for r in logged] == [("allow", "ok")], logged
    assert logged[0]["approval_token_id"] and logged[0]["step"] == f"{run_id}:note:1:1"
    # The token reached the gateway and nowhere else: not the journal, the run detail, its events or the queue.
    detail = (await client.get(f"/v1/runs/{run_id}")).text
    events = (await client.get(f"/v1/runs/{run_id}/events?follow=false")).text
    with tenant_scope("local"):
        work = json.dumps(await RunStore(EngineTransactions(engine)).work(run_id))
    for text in (detail, events, work):
        assert "approvalToken" not in text and "approval_token" not in text and "eyJ" not in text
