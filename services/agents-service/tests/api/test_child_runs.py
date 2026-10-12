"""Workflows as agent tools, by failure mode: an unpublished workflow offered or started, a paused child that is
invisible to Cases, a retried turn starting a second child, and a parent that invents a result for a paused child."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.api.child_runs import ChildRuns
from ops_agents.api.deps import Runtime
from ops_agents.store.graphs import metadata
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, scripted_model, sse_events

ASK = "Start workflow dispute_email: I was charged twice for order 4411 and want the second charge reversed."


@pytest.fixture
async def stack() -> AsyncIterator[tuple[AsyncClient, Runtime]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED),
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client, cast(Runtime, app.state.runtime)


async def agent_turn(client: AsyncClient, message: str) -> tuple[str, list[dict[str, Any]]]:
    tid = (await client.post("/v1/threads", json={"graph": "agent_wrapper", "metadata": {}})).json()["data"]["threadId"]
    body: dict[str, Any] = {"input": {"agent_id": "ag_dispute", "message": message, "kb_ids": []}}
    res = await client.post(f"/v1/threads/{tid}/runs/stream", json=body)
    assert res.status_code == 200, res.text
    return tid, sse_events(res.text)


async def test_only_granted_published_workflows_are_offered(stack: tuple[AsyncClient, Runtime]) -> None:
    _, rt = stack
    offers = await ChildRuns(rt).offers(["workflow:dispute_email", "workflow:never_published"])
    assert [(o.name, o.access) for o in offers] == [("workflow__dispute_email", "workflow")]


async def test_an_unpublished_workflow_is_refused(stack: tuple[AsyncClient, Runtime]) -> None:
    client, rt = stack
    parent, _ = await agent_turn(client, "Hello")
    outcome = await ChildRuns(rt).run(
        workflow="never_published", arguments={}, key="k-1", parent_thread_id=parent, parent_run_id=None
    )
    assert outcome.ok is False and "not published" in outcome.output["error"]
    assert rt.graph_store is not None
    assert [t["graph"] for t in await rt.graph_store.threads(None)] == ["agent_wrapper"]


async def test_a_paused_child_returns_a_handle_and_shows_in_cases(stack: tuple[AsyncClient, Runtime]) -> None:
    client, rt = stack
    parent, events = await agent_turn(client, ASK)
    text = "".join(str(e.get("data")) for e in events if e["event"] == "text")
    assert rt.graph_store is not None
    children = [t for t in await rt.graph_store.threads("dispute_email") if t["parent_thread_id"] == parent]
    assert len(children) == 1
    child = children[0]["id"]
    # The parent says it is waiting and names the child; it does not invent an outcome.
    assert f"waiting for a review: {child}" in text
    rows = (await client.get("/runs", params={"view": "needs_person", "page": 1, "pageSize": 25})).json()["data"]
    row = next(r for r in rows["data"] if r["id"] == child)
    assert row["state"] == "waiting" and row["trigger"].startswith("Started by agent")


async def test_a_retried_call_finds_the_same_child(stack: tuple[AsyncClient, Runtime]) -> None:
    client, rt = stack
    parent, _ = await agent_turn(client, "Hello")
    email = {"sender": "maria.lopez@example.com", "subject": "Disputed charge", "body": "Charged twice for 4411."}
    runner = ChildRuns(rt)
    first = await runner.run(
        workflow="dispute_email", arguments=email, key="call-7", parent_thread_id=parent, parent_run_id="run_x"
    )
    again = await runner.run(
        workflow="dispute_email", arguments=email, key="call-7", parent_thread_id=parent, parent_run_id="run_x"
    )
    assert first.output["threadId"] == again.output["threadId"]
    assert rt.graph_store is not None
    assert len(await rt.graph_store.threads("dispute_email")) == 1
    assert len(await rt.graph_store.runs(first.output["threadId"])) == 1
