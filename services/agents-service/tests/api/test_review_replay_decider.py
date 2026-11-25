"""A decision posted again to a review, by failure mode: the repeat answered from the recorded decision before the
decider check, so someone who may not decide the review resumed the run a decider's decision left waiting, or read the
decided review back as if they had decided it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypedDict, cast

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]
from langgraph.types import interrupt
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


class _Asked(TypedDict, total=False):
    answer: Any


def _asks_a_person(checkpointer: Any) -> Any:
    """A code graph that pauses on a step outside Reviews (a `manual` one) that names who asked for it. No shipped
    step of that kind names its asker today; this one does, so the resume and routing routes' decider check is seen."""

    async def ask(state: _Asked) -> _Asked:
        return {"answer": interrupt({"kind": "manual", "requested_by": "dana@harborpine.example", "reason": "Check"})}

    g = StateGraph(_Asked)
    g.add_node("ask", ask)  # pyright: ignore[reportUnknownMemberType]
    g.add_edge(START, "ask")
    g.add_edge("ask", END)
    return g.compile(checkpointer=checkpointer)  # pyright: ignore[reportUnknownMemberType]


async def test_a_paused_step_is_resumed_or_routed_only_by_who_may_decide_it(stack: tuple[AsyncClient, Runtime]) -> None:
    """The thread resume and route-to-people checked the team rule alone, so the person a paused step names as its
    asker answered it there while the two-person rule is on."""
    client, rt = stack
    rt.graphs["asks_a_person"] = _asks_a_person(rt.graphs["complex_workflow"].checkpointer)
    made = await client.post("/v1/threads", json={"graph": "asks_a_person", "metadata": {}}, headers=ASKER)
    tid = made.json()["data"]["threadId"]
    paused = await client.post(f"/v1/threads/{tid}/runs/stream", json={"input": {}}, headers=ASKER)
    assert any(e.get("event") == "interrupt" for e in sse_events(paused.text)), paused.text
    resume = {"resume": {"decision": "approved"}}
    own = await client.post(f"/v1/threads/{tid}/runs/stream", json=resume, headers=ASKER)
    assert own.status_code == 403, own.text
    routed = await client.post(f"/v1/threads/{tid}/route-to-people", json={"reason": "mine"}, headers=ASKER)
    assert routed.status_code == 403, routed.text
    other = await client.post(f"/v1/threads/{tid}/runs/stream", json=resume, headers=APPROVER)
    assert other.status_code == 200 and sse_events(other.text)[-1]["data"] == {"status": "done"}, other.text
