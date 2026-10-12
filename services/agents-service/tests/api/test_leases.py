"""E2 failure modes: two processes running one thread at once, a dead owner's lease blocking the thread forever, a
long node losing its lease while still running, and a thread whose process died mid-node never finishing.

Two app instances on one database and one checkpointer stand in for two processes; each has its own lease owner."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.api.runs import config
from ops_agents.api.sweeper import sweep_once
from ops_agents.store.graphs import metadata
from ops_agents.store.leases import thread_leases
from ops_service_kit.ids import now_iso
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, scripted_model, sse_events

EMAIL: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "seed" / "dispute_emails.json").read_text()
)[0]


class Proc:
    """One stand-in process: its app, client, runtime and model counter."""

    def __init__(self, app: FastAPI, client: AsyncClient, models: FakeGraphModels) -> None:
        self.app, self.client, self.models = app, client, models

    @property
    def rt(self) -> Runtime:
        return self.app.state.runtime


@pytest.fixture
async def procs() -> AsyncIterator[tuple[Proc, Proc]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    saver = InMemorySaver()
    # A short TTL so expiry happens inside a test; the background sweeper is idle and sweeps run by hand.
    settings = Settings(
        database_url="sqlite+aiosqlite://", seed_dir=SEED, lease_ttl_seconds=0.6, sweep_interval_seconds=3600
    )
    out: list[Proc] = []
    async with contextlib.AsyncExitStack() as stack:
        for _ in range(2):
            models = FakeGraphModels()
            app = create_app(settings, model=scripted_model(), engine=engine, checkpointer=saver, graph_models=models)
            await stack.enter_async_context(app.router.lifespan_context(app))
            client = await stack.enter_async_context(AsyncClient(transport=ASGITransport(app=app), base_url="http://p"))
            out.append(Proc(app, client, models))
        yield out[0], out[1]


async def until(condition: Callable[[], Awaitable[bool]], timeout: float = 10.0) -> None:
    """Waits for `condition` instead of a fixed sleep, so a slow machine waits longer rather than failing."""
    deadline = time.monotonic() + timeout
    while not await condition():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.02)


async def new_thread(p: Proc) -> str:
    return (await p.client.post("/v1/threads", json={"graph": "complex_workflow"})).json()["data"]["threadId"]


async def start(p: Proc, tid: str, delay_ms: int) -> Any:
    return await p.client.post(
        f"/v1/threads/{tid}/runs/stream", json={"input": {"email": EMAIL, "extract_delay_ms": delay_ms}}
    )


async def test_two_processes_cannot_run_one_thread(procs: tuple[Proc, Proc]) -> None:
    a, b = procs
    tid = await new_thread(a)
    ra, rb = await asyncio.gather(start(a, tid, 300), start(b, tid, 300))
    codes = sorted([ra.status_code, rb.status_code])
    assert codes == [200, 409], (ra.text, rb.text)
    refused = ra if ra.status_code == 409 else rb
    err = refused.json()["error"]
    assert err["code"] == "run_active" and "owner" in err["details"] and err["details"]["ageSeconds"] >= 0
    assert len(a.models.extracted) + len(b.models.extracted) == 3


async def test_stale_lease_from_dead_owner_is_reclaimed(procs: tuple[Proc, Proc]) -> None:
    a, _ = procs
    tid = await new_thread(a)
    async with a.rt.db.begin() as c:
        old = time.time() - 60
        await c.execute(
            thread_leases.insert().values(
                thread_id=tid,
                owner="dead-host:1",
                run_id="run_dead",
                acquired_at=old,
                heartbeat_at=old,
                expires_at=old + 1,
            )
        )
    res = await start(a, tid, 0)
    assert res.status_code == 200, res.text
    assert sse_events(res.text)[-1]["data"]["status"] == "interrupted"
    assert await a.rt.leases.held(tid) is None  # pyright: ignore[reportOptionalMemberAccess]


async def test_heartbeat_keeps_a_long_node_leased(procs: tuple[Proc, Proc]) -> None:
    a, b = procs
    tid = await new_thread(a)
    run = asyncio.create_task(start(a, tid, 1500))  # each extract outlasts the 0.6 s TTL
    await asyncio.sleep(1.0)
    second = await start(b, tid, 0)
    assert second.status_code == 409, second.text
    assert await sweep_once(b.rt) == []
    first = await run
    assert sse_events(first.text)[-1]["data"]["status"] == "interrupted"


async def test_sweeper_continues_a_thread_whose_process_died_mid_node(procs: tuple[Proc, Proc]) -> None:
    a, b = procs
    tid = await new_thread(a)
    graph = a.rt.graphs["complex_workflow"]
    store = a.rt.graph_store
    assert store is not None
    # Process A takes the lease and starts the run, then dies mid-extract: no release, no journal update.
    await store.start_run("run_killed", tid, "input", now_iso(), {"input": {"email": EMAIL}})
    await a.rt.leases.acquire(tid, "run_killed")  # pyright: ignore[reportOptionalMemberAccess]

    async def run_until_killed() -> None:
        async for _ in graph.astream({"email": EMAIL, "extract_delay_ms": 2000}, config(tid)):
            pass

    async def extracting() -> bool:
        return "extract" in (await graph.aget_state(config(tid))).next

    task = asyncio.create_task(run_until_killed())
    # Killed once the extracts are sleeping: a cancel that lands inside a database write would break the test's one
    # shared SQLite connection, which a real process death cannot do to another process.
    await until(extracting)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert (await graph.aget_state(config(tid))).next  # mid-run checkpoint with pending extracts
    leases = b.rt.leases
    assert leases is not None

    async def lease_expired() -> bool:  # nobody renews it
        return bool(await leases.expired())

    await until(lease_expired)

    recovered = await sweep_once(b.rt)
    assert len(recovered) == 1
    snap = await b.rt.graphs["complex_workflow"].aget_state(config(tid))
    assert snap.next == ("human",)
    assert (await store.run("run_killed") or {})["status"] == "crashed"
    assert (await store.run(recovered[0]) or {})["status"] == "interrupted"
    assert b.models.extracted and await b.rt.leases.held(tid) is None  # pyright: ignore[reportOptionalMemberAccess]
    # The recovery took a new generation, and the crashed run's journal names its owner and the nodes it was running.
    assert await b.rt.leases.generation_of(tid, recovered[0]) == 2  # pyright: ignore[reportOptionalMemberAccess]
    crashed = next(e["data"] for e in (await store.run("run_killed") or {})["events"] if e["event"] == "crashed")
    assert crashed["owner"] == a.rt.leases.owner and crashed["generation"] == 1  # pyright: ignore[reportOptionalMemberAccess]
    assert crashed["running"] and set(crashed["running"]) <= {"extract"}
