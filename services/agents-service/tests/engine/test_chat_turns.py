"""A chat reply as an engine_work turn, by failure mode: a reply whose process died is never finished, or finished by
paying for its model call again; a resumed reply's writes go out under new keys, so the gateway sends them again; a
team at its cap still starts a reply ahead of another team; two workers run one turn; and a turn past its time limit
is never ended.

Two app instances on one PostgreSQL database stand in for two processes, as tests/api/test_leases.py does; the queue's
own failure modes run on SQL Server too."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agent_kernel.testing import Answer
from ops_agent_kernel.types import TurnRequest
from ops_agents.api import chat_turns
from ops_agents.api.deps import Runtime
from ops_agents.api.engine_host import RunEvents, RunReviews, ThreadLeases
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.events import EventLog
from ops_agents.store.leases import Leases
from ops_agents.store.tenancy import tenant_scope
from ops_engine import default_registry
from ops_engine.ports import EnginePorts
from ops_engine.store import Work, WorkQueue
from ops_engine.store.tables import engine_work
from ops_engine.worker import TURN, Worker, WorkerHost
from ops_service_kit.errors import TooManyRequests
from ops_service_kit.http import Json
from ops_service_kit.settings import Settings
from ops_store.testing import DATABASES, NO_SQL_SERVER, sql_server_schema
from tests import conftest
from tests.api.test_chat import new_thread
from tests.conftest import SEED, FakeGraphModels, empty_engine, started

TTL = 0.6


class Killed(BaseException):
    """Stands in for SIGKILL: not an Exception, so nothing in the reply catches it."""


class Proc:
    def __init__(self, app: FastAPI, client: AsyncClient) -> None:
        self.app, self.client = app, client

    @property
    def rt(self) -> Runtime:
        return self.app.state.runtime


@pytest.fixture
def paid(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The scripted model's calls, counted: what a reply paid for, whichever process made it."""
    calls: list[int] = []
    inner = conftest.scripted

    def counted(messages: list[Json], tools: list[Json]) -> Answer:
        calls.append(1)
        return inner(messages, tools)

    monkeypatch.setattr(conftest, "scripted", counted)
    return calls


@pytest.fixture
async def procs(database_url: str, paid: list[int]) -> AsyncIterator[tuple[Proc, Proc]]:
    saver = InMemorySaver()
    settings = Settings(database_url=database_url, seed_dir=SEED, lease_ttl_seconds=TTL, sweep_interval_seconds=3600)
    out: list[Proc] = []
    async with contextlib.AsyncExitStack() as stack:
        engine = await stack.enter_async_context(empty_engine(database_url))
        for _ in range(2):
            app, client = await stack.enter_async_context(
                started(engine, settings, FakeGraphModels(), checkpointer=saver, base_url="http://p")
            )
            out.append(Proc(app, client))
        yield out[0], out[1]


def worker_on(rt: Runtime, *, turn_limit_s: float = 120.0) -> Worker:
    """A workflow worker with the chat runtime `rt`, as api/worker.py builds one."""
    owner = f"worker-{uuid4().hex[:6]}"
    host = WorkerHost(
        tx=EngineTransactions(rt.db),
        registry=default_registry(),
        ports=EnginePorts(tools=None, reviews=RunReviews()),  # type: ignore[arg-type]
        leases=ThreadLeases(Leases(rt.db, owner=owner, ttl=TTL)),
        events=RunEvents(EventLog(rt.db)),
        checkpointer=None,
        run_scope=tenant_scope,
        owner=owner,
        turn=chat_turns.take_over(rt),
        end_turn=chat_turns.end_late(rt),
        turn_limit_s=turn_limit_s,
    )
    return Worker(host)


async def die_mid_reply(a: Proc, monkeypatch: pytest.MonkeyPatch, thread_id: str) -> None:
    """Process A starts the reply and dies right after its model call was recorded: it lets nothing go, neither the
    thread's lease nor the turn's claim."""
    leases = a.rt.leases
    assert leases is not None

    async def kept(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(leases, "release", kept)
    monkeypatch.setattr(WorkQueue, "done", kept)

    async def lapses(*_a: Any, **_k: Any) -> bool:
        return False

    monkeypatch.setattr(WorkQueue, "renew", lapses)

    def killed(event: str, *_a: Any, **_k: Any) -> None:
        if event == "model_call":
            raise Killed

    monkeypatch.setattr("ops_agents.api.budgets.emit", killed)
    with contextlib.suppress(Killed, BaseExceptionGroup):
        await a.client.post(
            f"/chat/threads/{thread_id}/messages",
            json={"content": "What is the daily wire limit for a personal account?"},
            headers={"Accept": "text/event-stream"},
        )
    monkeypatch.undo()


async def take_over(b: Proc, thread_id: str) -> None:
    """Waits for the dead process's claim to lapse, then runs a worker until it took the turn over."""
    await asyncio.sleep(TTL * 2)
    w = worker_on(b.rt)
    deadline = time.monotonic() + 10
    while True:
        work = await w.queue.claim()
        assert work is not None or time.monotonic() < deadline, "no worker took the turn over"
        if work is not None and work.kind == TURN and work.run_id == thread_id:
            await w.process(work)
            return
        await asyncio.sleep(0.05)


async def test_a_reply_whose_process_died_is_finished_by_a_worker_without_a_second_model_call(
    procs: tuple[Proc, Proc], paid: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = procs
    tid = (await new_thread(a.client))["id"]
    await die_mid_reply(a, monkeypatch, tid)
    before = len(paid)
    assert before >= 1, "the reply died before its model call"
    await take_over(b, tid)
    store = b.rt.graph_store
    assert store is not None
    with tenant_scope("local"):
        runs = [(r.kind, r.status) for r in await store.runs(tid)]
    assert ("recovery", "done") in runs, runs
    assert len(paid) == before, f"the takeover paid for {len(paid) - before} model calls again"


async def test_a_resumed_reply_sends_its_writes_under_the_keys_it_had(
    procs: tuple[Proc, Proc], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = procs
    tid = (await new_thread(a.client))["id"]
    asked: list[tuple[str, str]] = []
    real = TurnRequest.__init__

    def seen(self: TurnRequest, *args: Any, **kw: Any) -> None:
        real(self, *args, **kw)
        asked.append((self.run_id, self.turn_id))

    with monkeypatch.context() as m:
        m.setattr(TurnRequest, "__init__", seen)
        await die_mid_reply(a, m, tid)
        m.setattr(TurnRequest, "__init__", seen)
        await take_over(b, tid)
    # A write's key is run_id:turn_id:step:n (ops_agent_kernel): the same ids mean the gateway answers a write the
    # dead process sent from its record instead of sending it again.
    reply = [ids for ids in asked if not ids[0].startswith("memory:")]  # memory extraction is a turn of its own
    assert len(reply) >= 2 and len(set(reply)) == 1, asked


@pytest.fixture(scope="module", params=DATABASES)
def url(request: pytest.FixtureRequest) -> Iterator[str]:
    if request.param == "postgresql":
        yield request.getfixturevalue("database_url")
        return
    with sql_server_schema("agents", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")) as ms:
        if ms is None:
            pytest.skip(NO_SQL_SERVER)
        yield ms


@pytest.fixture
async def engine(url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(url)
    yield e
    await e.dispose()


class Runs:
    """A turn handler that counts the turns it ran, slowly enough for a second worker to try the same row."""

    def __init__(self) -> None:
        self.ran: list[str] = []

    async def __call__(self, work: Work) -> float | None:
        self.ran.append(work.run_id)
        await asyncio.sleep(0.3)
        return None


def turn_worker(engine: AsyncEngine, turn: Runs, cap: int | None = None) -> Worker:
    owner = f"w-{uuid4().hex[:6]}"
    host = WorkerHost(
        tx=EngineTransactions(engine),
        registry=default_registry(),
        ports=EnginePorts(tools=None, reviews=RunReviews()),  # type: ignore[arg-type]
        leases=ThreadLeases(Leases(engine, owner=owner, ttl=5.0)),
        events=RunEvents(EventLog(engine)),
        checkpointer=None,
        run_scope=tenant_scope,
        owner=owner,
        team_cap=cap,
        turn=turn,
    )
    return Worker(host)


async def queue_turn(engine: AsyncEngine, tenant: str, team: str, *, created_at: str | None = None) -> str:
    thread = f"thr_{uuid4().hex[:10]}"
    with tenant_scope(tenant):
        q = WorkQueue(EngineTransactions(engine), "api", 5.0)
        row, _ = await q.enqueue(
            thread, TURN, f"turn:{thread}", {"threadId": thread, "turnId": thread, "teamId": team}, team_id=team
        )
        if created_at is not None:
            async with EngineTransactions(engine).tenant_tx() as c:
                await c.execute(engine_work.update().where(engine_work.c.id == row["id"]).values(created_at=created_at))
    return thread


async def claim_ours(w: Worker, threads: set[str]) -> list[Work]:
    """Claims until the queue is empty, keeping this test's turns; other tests' rows are dropped."""
    got: list[Work] = []
    while (work := await w.queue.claim()) is not None:
        if work.run_id in threads:
            got.append(work)
    return got


async def test_a_team_at_its_cap_is_refused_a_reply_while_another_team_starts_one(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    a1 = await queue_turn(engine, tenant, "team_a")
    w = turn_worker(engine, Runs(), cap=1)
    (running,) = await claim_ours(w, {a1})
    a2, b1 = await queue_turn(engine, tenant, "team_a"), await queue_turn(engine, tenant, "team_b")
    # Only team_b's turn is claimed while team_a's one slot is busy.
    assert [x.run_id for x in await claim_ours(w, {a2, b1})] == [b1]
    rt = Runtime.__new__(Runtime)
    rt.db, rt.settings = engine, Settings(engine_team_cap=1)
    rt.leases = Leases(engine, owner="api", ttl=5.0)
    with tenant_scope(tenant):
        with pytest.raises(TooManyRequests) as refused:
            await chat_turns.refuse_at_capacity(rt, "team_a")
        assert refused.value.code == "team_at_capacity"
        await chat_turns.refuse_at_capacity(rt, "team_c")
    assert running.run_id == a1


async def test_two_workers_never_run_one_turn(engine: AsyncEngine) -> None:
    tenant, ran = f"t-{uuid4().hex[:8]}", Runs()
    thread = await queue_turn(engine, tenant, "team_a")
    workers = [turn_worker(engine, ran) for _ in range(2)]

    async def one(w: Worker) -> None:
        for work in await claim_ours(w, {thread}):
            await w.process(work)

    await asyncio.gather(*(one(w) for w in workers))
    assert ran.ran == [thread], ran.ran


async def test_a_turn_past_its_time_limit_is_ended_not_continued(procs: tuple[Proc, Proc]) -> None:
    a, b = procs
    tid = (await new_thread(a.client))["id"]
    store, leases = a.rt.graph_store, a.rt.leases
    assert store is not None and leases is not None
    # A reply queued five minutes ago whose process died holding its thread.
    await leases.acquire(tid, "run_dead")
    async with a.rt.db.begin() as c:
        await c.execute(sa.text("UPDATE thread_leases SET expires_at = 0 WHERE thread_id = :t"), {"t": tid})
    owner = await store.owner_of(tid)
    assert owner is not None
    team = owner[1]
    old = "2026-01-01T00:00:00+00:00"
    with tenant_scope("local"):
        q = WorkQueue(EngineTransactions(a.rt.db), "api", TTL)
        await q.enqueue(tid, TURN, f"turn:{tid}", {"threadId": tid, "turnId": "run_dead", "teamId": team}, team_id=team)
        async with EngineTransactions(a.rt.db).tenant_tx() as c:
            await c.execute(engine_work.update().where(engine_work.c.run_id == tid).values(created_at=old))
    w = worker_on(b.rt, turn_limit_s=120.0)
    (work,) = await claim_ours(w, {tid})
    await w.process(work)
    row = await _status(a.rt.db, tid)
    assert row == "failed", row
    assert await leases.held(tid) is None, "the late turn still holds its thread"


async def _status(db: AsyncEngine, thread: str) -> str:
    async with db.connect() as c:
        return str(
            (await c.execute(sa.select(engine_work.c.status).where(engine_work.c.run_id == thread))).scalar_one()
        )
