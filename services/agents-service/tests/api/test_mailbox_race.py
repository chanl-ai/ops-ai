"""Two Runtime processes on one PostgreSQL: a message arriving at process B while process A has created the case
but not yet started its first run. Before the fix the reply found no case (the ledger is written only after a run)
or saw a case with no run and treated it as finished, and either way opened a second case."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.api.app import create_app
from ops_agents.api.channels.mailbox.adapter import MailboxAdapter, message_key
from ops_agents.api.channels.mailbox.fake_graph import FakeMailSource
from ops_agents.api.deps import Runtime
from ops_agents.store.graphs import graph_threads
from ops_agents.store.leases import thread_lock
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, scripted_model

ROOT = SEED.parents[2]
FIRST: dict[str, Any] = json.loads((SEED.parent / "mailbox" / "delta_messages.json").read_text())[0]


class PausingClient(AsyncClient):
    """Process A's client: after the case is created, waits until told to start its run."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.created = asyncio.Event()
        self.go = asyncio.Event()

    async def post(self, url: Any, *args: Any, **kwargs: Any) -> Response:
        res = await super().post(url, *args, **kwargs)
        if str(url) == "/v1/threads" and not self.created.is_set():
            self.created.set()
            await self.go.wait()
        return res


@asynccontextmanager
async def process(client_class: type[AsyncClient]) -> AsyncGenerator[tuple[AsyncClient, Runtime]]:
    """One Runtime process: its own connection pool, checkpointer and lease owner, on the shared database."""
    settings = Settings(seed_dir=SEED, timer_poll_seconds=0, sweep_interval_seconds=3600)
    app: FastAPI = create_app(
        settings,
        model=scripted_model(),
        engine=create_async_engine(settings.database_url),
        graph_models=FakeGraphModels(),
    )
    async with (
        app.router.lifespan_context(app),
        client_class(transport=ASGITransport(app=app), base_url="http://m") as client,
    ):
        yield client, app.state.runtime


@pytest.fixture(scope="module", autouse=True)
def migrated() -> None:
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


def mail(local: str) -> dict[str, Any]:
    m = copy.deepcopy(FIRST)
    m.pop("_fixture", None)
    m["id"] = f"AAMk-{local}"
    m["internetMessageId"] = f"<{local}@example.com>"
    return m


def reply_to(original: dict[str, Any], local: str) -> dict[str, Any]:
    r = mail(local)
    r["subject"] = f"Re: {original['subject']}"
    r["attachments"] = []
    r["internetMessageHeaders"] = [{"name": "In-Reply-To", "value": original["internetMessageId"]}]
    return r


async def cases(rt: Runtime, deployment: str) -> list[dict[str, Any]]:
    assert rt.graph_store is not None
    q = graph_threads.select().where(graph_threads.c.deployment_id == deployment)
    async with rt.graph_store.engine.connect() as c:
        return [dict(r) for r in (await c.execute(q)).mappings()]


async def race(second: dict[str, Any], first: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Process A takes `first`; while its case exists with no run yet, process B takes `second`."""
    dep = f"dep_race_{uuid4().hex[:8]}"
    async with AsyncExitStack() as stack:
        client_a, rt_a = await stack.enter_async_context(process(PausingClient))
        client_b, rt_b = await stack.enter_async_context(process(AsyncClient))
        assert isinstance(client_a, PausingClient)
        r = await client_a.post("/v1/deployments", json={"id": dep, "graph": "complex_workflow", "channel": "mailbox"})
        client_a.created.clear()
        assert r.status_code == 201, r.text
        assert rt_a.channels is not None and rt_b.channels is not None
        a = MailboxAdapter(client_a, FakeMailSource([first]), rt_a.channels, dep)
        b = MailboxAdapter(client_b, FakeMailSource([second]), rt_b.channels, dep)
        poll_a = asyncio.create_task(a.poll())
        await client_a.created.wait()
        await b.poll()  # in the window: A's case exists, its first run has not started
        client_a.go.set()
        await poll_a
        found = await cases(rt_a, dep)
        inbox: list[dict[str, Any]] = []
        if found:
            inbox = (await client_a.get(f"/v1/threads/{found[0]['id']}/inbox")).json()["data"]
        return found, inbox


async def test_a_redelivery_during_the_first_delivery_opens_one_case() -> None:
    m = mail(f"m-{uuid4().hex[:8]}")
    found, _ = await race(m, m)
    assert len(found) == 1


async def test_a_reply_during_the_first_delivery_joins_its_case() -> None:
    m = mail(f"m-{uuid4().hex[:8]}")
    r = reply_to(m, f"r-{uuid4().hex[:8]}")
    found, inbox = await race(r, m)
    assert len(found) == 1, [c["external_key"] for c in found]
    assert [(e["messageKey"], e["status"]) for e in inbox] == [(message_key(r), "delivered")]


async def test_a_lease_cannot_be_taken_while_a_delivery_looks_at_the_thread() -> None:
    """A delivery holds the thread's lock from its look at the thread to its inbox write; a run taking the lease in
    between would make the message look delivered to a run that never reads it."""
    async with process(AsyncClient) as (_, rt):
        assert rt.leases is not None and rt.graph_store is not None
        thread = f"gth_lock_{uuid4().hex[:8]}"
        async with rt.graph_store.engine.connect() as conn:
            tx = await conn.begin()
            await thread_lock(conn, thread)  # as deliver() does
            acquire = asyncio.create_task(rt.leases.acquire(thread, "run_racing"))
            await asyncio.sleep(0.5)
            assert not acquire.done(), "the lease was taken while the delivery held the thread"
            await tx.commit()
        assert await acquire >= 1
        await rt.leases.release(thread, "run_racing")
