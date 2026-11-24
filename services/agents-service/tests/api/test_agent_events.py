"""The agent wrapper's events, by failure mode: a chat reader missing what it must show (the whole tool call, the
citations, which model answered), an approval that forgets who asked, and the asker deciding their own request
when policy forbids it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.store.base import metadata
from ops_agents.store.events import thread_events
from ops_engine.store import metadata as engine_metadata
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model, signed_in, step_up, with_sign_in

ASKER = "dana@harborpine.example"


def app_for(**fields: Any) -> Any:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, **fields)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        knowledge=fixture_knowledge(),
        auth=with_sign_in(settings),
    )
    return app, engine


async def client_for(**fields: Any) -> AsyncIterator[AsyncClient]:
    app, engine = app_for(**fields)
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        client.app = app  # type: ignore[attr-defined]
        yield client


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async for c in client_for():
        yield c


async def agent_run(client: AsyncClient, message: str) -> str:
    # The asker starts the thread they run: an agent's conversation is read by the person it is for.
    made = await client.post(
        "/v1/threads", json={"graph": "agent_wrapper", "metadata": {}}, headers={"X-Dev-User": ASKER}
    )
    tid = made.json()["data"]["threadId"]
    body = {"input": {"agent_id": "ag_fraud", "message": message, "kb_ids": ["kb_people"], "requested_by": ASKER}}
    res = await client.post(f"/v1/threads/{tid}/runs/stream", json=body, headers={"X-Dev-User": ASKER})
    assert res.status_code == 200, res.text
    return tid


async def events(client: AsyncClient, tid: str) -> list[dict[str, Any]]:
    rt = cast(Runtime, client.app.state.runtime)  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert rt.graph_store is not None
    async with rt.graph_store.engine.connect() as c:
        rows = await c.execute(
            thread_events.select().where(thread_events.c.thread_id == tid).order_by(thread_events.c.seq)
        )
        return [{"type": r.type, "node": r.node, "data": r.data} for r in rows.all()]


async def test_a_cited_answer_logs_text_citations_and_the_model(client: AsyncClient) -> None:
    log = await events(client, await agent_run(client, "What is the daily wire limit for a personal account?"))
    types = [e["type"] for e in log]
    assert "text" in types and types[-1] == "finished"
    citation = next(e["data"] for e in log if e["type"] == "citation")
    assert citation[0]["documentId"] == "doc_wire_limits" and citation[0]["n"] == 1
    turn = next(e["data"] for e in log if e["type"] == "turn")
    assert turn["model"].startswith("function:scripted")


async def test_a_gated_call_logs_the_whole_call_and_who_asked(client: AsyncClient) -> None:
    log = await events(client, await agent_run(client, "Place a 24-hour hold on wire W-88213"))
    call = next(e["data"] for e in log if e["type"] == "tool_call")
    assert {"id", "tool", "server", "access", "input", "status"} <= set(call)
    assert call["tool"] == "place_wire_hold" and call["access"] == "write"
    waiting = next(e["data"] for e in log if e["type"] == "waiting_review")
    assert waiting["payload"]["requested_by"] == ASKER


async def test_the_asker_decides_their_chat_request_only_while_they_hold_approvals_decide(client: AsyncClient) -> None:
    # Signed in as a Reviewer the asker lacks the cell; as the dev caller she holds every cell.
    for who, expected in ((signed_in(ASKER), 403), ({"X-Dev-User": ASKER}, 200)):
        tid = await agent_run(client, "Place a 24-hour hold on wire W-88213")
        body = {"decision": "approved", "stepUpToken": await step_up(client, ASKER)}
        res = await client.post(f"/reviews/{tid}/decision", json=body, headers=who)
        assert res.status_code == expected, res.text
