"""A review step approving a run's write waits for a person's click, through the real start route, worker and decision
route on PostgreSQL, by failure mode: a run started by someone who may decide its review approves its own write
without anyone seeing it; with the two-person rule on, the starter decides it instead of a second person."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api.app import create_app
from ops_agents.api.engine_host import RunEvents, RunReviews, ThreadLeases
from ops_agents.api.worker import enter_run
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.events import EventLog
from ops_agents.store.leases import Leases
from ops_agents.store.tenancy import tenant_scope
from ops_engine import default_registry
from ops_engine.ports import EnginePorts
from ops_engine.worker import Worker, WorkerHost
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_lifecycle import (  # noqa: F401
    JAMES,
    MAYA,
    data,
    drain,
    engine,  # pyright: ignore[reportUnusedImport]
    publish,
    save,
)
from tests.engine.test_worker import CountingTools


def note(wid: str) -> dict[str, Any]:
    """A review that approves one customer note; the note is written only on approve."""

    def node(nid: str, kind: str, **params: Any) -> dict[str, Any]:
        return {"id": nid, "type": kind, "typeVersion": 1, "name": nid.capitalize(), "parameters": params}

    return {
        "schemaVersion": 2,
        "id": wid,
        "name": "Note",
        "nodes": [
            node("start", "ops.trigger.request"),
            node("review", "ops.flow.humanReview", title="Write the note", approves="note"),
            node("note", "ops.action.tool", operation="add_customer_note", input={"text": "$.input.name"},
                 approvedBy="review"),
            node("ok", "ops.flow.end", outcome="noted"),
            node("no", "ops.flow.end", outcome="rejected"),
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "review", "port": "in"}},
            {"from": {"node": "review", "port": "approve"}, "to": {"node": "note", "port": "in"}},
            {"from": {"node": "review", "port": "reject"}, "to": {"node": "no", "port": "in"}},
            {"from": {"node": "note", "port": "ok"}, "to": {"node": "ok", "port": "in"}},
            {"from": {"node": "note", "port": "refused"}, "to": {"node": "no", "port": "in"}},
            {"from": {"node": "note", "port": "error"}, "to": {"node": "no", "port": "in"}},
        ],
    }  # fmt: skip


def _worker(engine: AsyncEngine, tools: CountingTools) -> Worker:  # noqa: F811
    """The service worker's review wiring (api/worker.py) over test tools."""
    owner = f"test-{uuid4().hex[:6]}"
    host = WorkerHost(
        tx=EngineTransactions(engine),
        registry=default_registry(),
        ports=EnginePorts(tools=tools, reviews=RunReviews()),
        leases=ThreadLeases(Leases(engine, owner=owner, ttl=6.0)),
        events=RunEvents(EventLog(engine)),
        checkpointer=InMemorySaver(),
        run_scope=tenant_scope,
        owner=owner,
        enter_run=enter_run,
    )
    return Worker(host)


@pytest.fixture
async def client(engine: AsyncEngine, request: pytest.FixtureRequest) -> AsyncIterator[httpx.AsyncClient]:  # noqa: F811
    settings = Settings(
        database_url=str(engine.url),
        seed_dir=SEED,
        registry_auto_approve=False,
        dev_policies={"requesterMayDecide": request.param},
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
        yield c


@pytest.mark.parametrize(
    ("client", "decider"),
    [(True, JAMES), (False, MAYA)],
    ids=["asker-may-decide", "two-person-rule"],
    indirect=["client"],
)
async def test_a_builders_run_waits_at_its_review_until_someone_who_may_decide_clicks(
    client: httpx.AsyncClient,
    engine: AsyncEngine,  # noqa: F811
    decider: dict[str, str],
) -> None:
    """James, a Builder, holds reviews.decide. His run holds at the review and writes nothing; with the two-person
    rule on, he is refused and Maya decides. Either way the note is written once, after the click."""
    wid = f"wf_{uuid4().hex[:8]}"
    await save(client, note(wid))
    await publish(client, wid)
    started = await client.post("/v1/runs", json={"workflowId": wid, "input": {"name": "Called back"}}, headers=JAMES)
    run_id = data(started)["runId"]
    tools = CountingTools()
    w = _worker(engine, tools)
    await drain(w)

    run = data(await client.get(f"/v1/runs/{run_id}", headers=JAMES))
    assert (run["status"], tools.calls) == ("waiting", []), run
    if decider is MAYA:
        own = await client.post(f"/reviews/{run_id}/decision", json={"decision": "approved"}, headers=JAMES)
        assert own.status_code == 403, own.text
    data(await client.post(f"/reviews/{run_id}/decision", json={"decision": "approved"}, headers=decider))
    await drain(w)
    run = data(await client.get(f"/v1/runs/{run_id}", headers=JAMES))
    assert (run["status"], run.get("outcome"), len(tools.calls)) == ("succeeded", "noted", 1), run
