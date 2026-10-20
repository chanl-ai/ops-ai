"""The person who asked a chat agent decides its action unless the tenant switched requesterMayDecide off (c-186), by
failure mode: the asker refused while the policy is open, the asker deciding once it is off, and a namesake taken for
the asker."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.graphs import metadata
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model, sse_events, step_up

DANA, LEE = "dana@northfieldbank.com", "lee@northfieldbank.com"


async def client(**policies: bool) -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, dev_policies=policies)
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.fixture
async def strict() -> AsyncIterator[AsyncClient]:
    async for c in client(requesterMayDecide=False):
        yield c


@pytest.fixture
async def open_() -> AsyncIterator[AsyncClient]:
    async for c in client():
        yield c


async def _dana_asks(c: AsyncClient) -> str:
    as_dana = {"X-Dev-User": DANA}
    res = await c.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_people"]}, headers=as_dana)
    thread = res.json()["data"]
    sent = await c.post(
        f"/chat/threads/{thread['id']}/messages",
        json={"content": "Place a 24-hour hold on wire W-88213"},
        headers={**as_dana, "Accept": "text/event-stream"},
    )
    events = sse_events(sent.text)
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    return f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"


async def test_while_the_policy_is_open_the_person_who_asked_approves(open_: AsyncClient) -> None:
    url = await _dana_asks(open_)
    token = await step_up(open_, DANA)
    own = await open_.post(url, json={"type": "approve", "stepUpToken": token}, headers={"X-Dev-User": DANA})
    assert own.status_code == 200, own.text


async def test_the_person_who_asked_cannot_approve(strict: AsyncClient) -> None:
    as_dana = {"X-Dev-User": DANA}
    res = await strict.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_people"]}, headers=as_dana)
    thread = res.json()["data"]
    sent = await strict.post(
        f"/chat/threads/{thread['id']}/messages",
        json={"content": "Place a 24-hour hold on wire W-88213"},
        headers={**as_dana, "Accept": "text/event-stream"},
    )
    events = sse_events(sent.text)
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"

    own = await strict.post(url, json={"type": "approve", "stepUpToken": await step_up(strict, DANA)}, headers=as_dana)
    assert own.status_code == 403, own.text
    assert "someone else" in own.json()["error"]["message"]
    other = await strict.post(
        url, json={"type": "approve", "stepUpToken": await step_up(strict, LEE)}, headers={"X-Dev-User": LEE}
    )
    assert other.status_code == 200, other.text


async def test_someone_sharing_the_askers_name_is_not_the_asker(strict: AsyncClient) -> None:
    # The dev user (James Richardson, j.richardson@...) asks; another subject whose display name is the same string
    # decides. Compared by name they would be one person; by subject they are two.
    res = await strict.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_people"]})
    thread = res.json()["data"]
    sent = await strict.post(
        f"/chat/threads/{thread['id']}/messages",
        json={"content": "Place a 24-hour hold on wire W-88213"},
        headers={"Accept": "text/event-stream"},
    )
    events = sse_events(sent.text)
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"
    namesake = "James Richardson"
    token = await step_up(strict, namesake)
    decided = await strict.post(url, json={"type": "approve", "stepUpToken": token}, headers={"X-Dev-User": namesake})
    assert decided.status_code == 200, decided.text
