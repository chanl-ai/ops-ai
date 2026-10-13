"""The thread event log, by failure mode: events written only at run end, seq restarting per run, a re-attach that
repeats or skips events, a team stream that leaks another team's threads, a decision with no event, and an approval
by the workflow's own principal."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_config
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.api.routers.events import team_frames
from ops_agents.graphs.models import Grade
from ops_agents.store.events import thread_events
from ops_agents.store.graphs import metadata
from ops_identity.fastapi import DEV_TEAM
from ops_service_kit.settings import Settings
from tests.api.test_graphs import EMAILS, run
from tests.conftest import SEED, FakeGraphModels, decide, last_run, scripted_model, sse_events

ROOT = Path(__file__).parents[2]
SHAPE = {"id", "seq", "type", "threadId", "runId", "node", "at", "data"}


class Spy(FakeGraphModels):
    """Reads the event log from inside the run, at the grade step."""

    def __init__(self) -> None:
        super().__init__()
        self.rt: Runtime | None = None
        self.seen_mid_run: list[str] = []

    async def grade(self, email: str, draft: str) -> Grade:
        assert self.rt is not None and self.rt.graph_store is not None
        thread_id = (get_config().get("configurable") or {})["thread_id"]
        q = (
            sa.select(thread_events.c.type, thread_events.c.node)
            .where(thread_events.c.thread_id == thread_id)
            .order_by(thread_events.c.seq)
        )
        async with self.rt.graph_store.engine.connect() as c:
            self.seen_mid_run = [f"{t}:{n}" for t, n in (await c.execute(q)).all()]
        return await super().grade(email, draft)


@pytest.fixture(scope="module")
def migrated() -> str:
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    return Settings().database_url


@pytest.fixture
async def pg_stack(migrated: str) -> AsyncIterator[tuple[AsyncClient, Spy]]:
    """PostgreSQL, where events are written as they happen (SQLite writes them at run end; see runs.execute)."""
    spy = Spy()
    app = create_app(
        Settings(seed_dir=SEED),
        model=scripted_model(),
        engine=create_async_engine(migrated),
        checkpointer=InMemorySaver(),
        graph_models=spy,
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        spy.rt = app.state.runtime
        yield client, spy


@pytest.fixture
async def stack() -> AsyncIterator[tuple[AsyncClient, Runtime, Spy]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    spy = Spy()
    app = create_app(
        Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED),
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=spy,
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        spy.rt = app.state.runtime
        yield client, app.state.runtime, spy


async def paused(client: AsyncClient, team: str | None = None) -> tuple[str, str]:
    headers = {"X-Team-Id": team} if team else {}
    res = await client.post("/v1/threads", json={"graph": "complex_workflow", "metadata": {}}, headers=headers)
    tid = res.json()["data"]["threadId"]
    events = await run(client, tid, {"input": {"email": EMAILS[0]}})
    return tid, events[0]["runId"]


async def reattach(client: AsyncClient, tid: str, run_id: str, after: int = 0) -> list[dict[str, Any]]:
    res = await client.get(f"/v1/threads/{tid}/runs/{run_id}/events", params={"after": after, "follow": "false"})
    assert res.status_code == 200, res.text
    return sse_events(res.text)


async def test_events_are_written_as_they_happen(pg_stack: tuple[AsyncClient, Spy]) -> None:
    client, spy = pg_stack
    await paused(client)
    # Read from inside the run, before it ended: the started event and every extract step are already stored.
    assert spy.seen_mid_run[0] == "started:None"
    assert spy.seen_mid_run.count("node:extract") == 6  # start and end of three fan-out tasks


async def test_reattach_from_a_cursor_returns_the_rest_in_the_designed_shape(
    stack: tuple[AsyncClient, Runtime, Spy],
) -> None:
    client, _, _ = stack
    tid, run_id = await paused(client)
    every = await reattach(client, tid, run_id)
    assert all(set(e) == SHAPE for e in every)
    assert [e["seq"] for e in every] == list(range(1, len(every) + 1))
    assert every[0]["type"] == "started" and "waiting_review" in [e["type"] for e in every]
    rest = await reattach(client, tid, run_id, after=every[4]["seq"])
    assert rest == every[5:]


async def test_seq_rises_per_thread_across_runs_and_decide_is_an_event(stack: tuple[AsyncClient, Runtime, Spy]) -> None:
    client, rt, _ = stack
    tid, first_run = await paused(client)
    first = await reattach(client, tid, first_run)
    await decide(client, tid)
    resumed = await last_run(client, tid)
    second = await reattach(client, tid, resumed["runId"])
    assert second[0]["seq"] == first[-1]["seq"] + 2  # the decided event sits between the two runs
    assert second[-1]["type"] == "finished" and first[-1]["node"] == "human"
    assert rt.graph_store is not None
    async with rt.graph_store.engine.connect() as c:
        decided = (await c.execute(thread_events.select().where(thread_events.c.type == "decided"))).all()
    assert len(decided) == 1 and decided[0].data["decision"] == "approved"


async def test_team_stream_carries_only_that_teams_lifecycle(stack: tuple[AsyncClient, Runtime, Spy]) -> None:
    client, rt, _ = stack
    await paused(client, team="team_cards")
    await paused(client, team="team_lending")
    frames = [f async for f in team_frames(rt, "team_cards", 0, follow=False)]
    events = [json.loads(f["data"]) for f in frames]
    assert [f["event"] for f in frames] == ["thread.started", "thread.waiting_review"]
    assert len({e["threadId"] for e in events}) == 1
    after = [f async for f in team_frames(rt, "team_cards", int(frames[0]["id"]), follow=False)]
    assert [f["event"] for f in after] == ["thread.waiting_review"]
    assert [f async for f in team_frames(rt, "team_none", 0, follow=False)] == []


async def test_team_stream_follows_new_events(stack: tuple[AsyncClient, Runtime, Spy]) -> None:
    client, rt, _ = stack
    stream = team_frames(rt, DEV_TEAM, 0, follow=True)  # paused() names no team: the dev user's default
    await paused(client)
    seen = [(await anext(stream))["event"], (await anext(stream))["event"]]
    await stream.aclose()
    assert seen == ["thread.started", "thread.waiting_review"]


async def test_the_workflows_own_principal_cannot_approve(stack: tuple[AsyncClient, Runtime, Spy]) -> None:
    client, _, _ = stack
    tid, _ = await paused(client)
    res = await client.post(
        f"/v1/threads/{tid}/approvals", json={}, headers={"X-Dev-User": "workflow:complex_workflow"}
    )
    assert res.status_code == 403, res.text
    assert (await client.post(f"/v1/threads/{tid}/approvals", json={})).status_code == 200
