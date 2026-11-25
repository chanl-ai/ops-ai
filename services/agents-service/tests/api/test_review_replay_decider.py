"""A decision posted again to a review, by failure mode: the repeat answered from the recorded decision before the
decider check, so someone who may not decide the review resumed the run a decider's decision left waiting, or read the
decided review back as if they had decided it."""

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
from ops_engine.store import metadata as engine_metadata
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model, sse_events

# The four-eyes rule on: the person who asked for the write may not decide it, every other dev caller may.
ASKER, APPROVER = {"X-Dev-User": "dana@harborpine.example"}, {"X-Dev-User": "lee@harborpine.example"}
WRITE = 'call request_document {"customerId": "C-1042", "document": "proof of address", "reason": "Moved"}'


@pytest.fixture
async def stack(graph_models: FakeGraphModels) -> AsyncIterator[tuple[AsyncClient, Runtime]]:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, dev_policies={"requesterMayDecide": False})
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=graph_models,
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c, app.state.runtime


async def _hold(client: AsyncClient) -> str:
    res = await client.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=ASKER)
    thread = str(res.json()["data"]["id"])
    sent = await client.post(
        f"/chat/threads/{thread}/messages", json={"content": WRITE}, headers={**ASKER, "Accept": "text/event-stream"}
    )
    assert any(e["type"] == "widget" for e in sse_events(sent.text)), "the write stops for approval"
    return thread


async def _resumes(client: AsyncClient, thread: str) -> int:
    """The runs that resumed the thread from its decision."""
    runs = (await client.get(f"/v1/threads/{thread}/runs", headers=ASKER)).json()["data"]
    return sum(1 for r in cast(list[dict[str, Any]], runs) if r["kind"] == "resume")


async def test_a_non_decider_cannot_replay_a_decision_and_the_decider_still_can(
    stack: tuple[AsyncClient, Runtime],
) -> None:
    client, rt = stack
    thread = await _hold(client)
    assert rt.leases is not None
    # The decider's decision is recorded while another run holds the thread, so it waits to be resumed.
    await rt.leases.acquire(thread, "run_other")
    held = await client.post(f"/reviews/{thread}/decision", json={"decision": "approved"}, headers=APPROVER)
    assert (held.status_code, held.json()["error"]["code"]) == (409, "run_active"), held.text
    await rt.leases.release(thread, "run_other")

    # The asker posts the same decision: refused before the recorded decision is replayed, and nothing resumes.
    replay = await client.post(f"/reviews/{thread}/decision", json={"decision": "approved"}, headers=ASKER)
    assert replay.status_code == 403, replay.text
    assert await _resumes(client, thread) == 0

    # The decider's repeat resumes the run once; a second repeat sends nothing more.
    for _ in range(2):
        again = await client.post(f"/reviews/{thread}/decision", json={"decision": "approved"}, headers=APPROVER)
        assert (again.status_code, again.json()["data"]["status"]) == (200, "approved"), again.text
    assert await _resumes(client, thread) == 1

    # Once resumed, the asker's repeat is still refused, the different decision included.
    for decision in ("approved", "rejected"):
        late = await client.post(f"/reviews/{thread}/decision", json={"decision": decision}, headers=ASKER)
        assert late.status_code == 403, late.text
