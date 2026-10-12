"""Mailbox channel (E6), by failure mode: a redelivered message opening a second case, replies on a running case
arriving out of order, a poll that dies mid-way duplicating cases, a message with no Message-ID escaping dedup, a
paused deployment still opening cases, and a reply to a finished case getting lost. The full fixture run checks the
counts end to end and that attachments reach the graph only as file ids."""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.api.channels.inbox import drain
from ops_agents.api.channels.mailbox.adapter import MailboxAdapter, message_key, references, text_at
from ops_agents.api.channels.mailbox.fake_graph import FakeMailSource
from ops_agents.api.deps import Runtime
from ops_agents.store.graphs import graph_threads, metadata
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, scripted_model

FIXTURE: list[dict[str, Any]] = json.loads((SEED.parent / "mailbox" / "delta_messages.json").read_text())
DEP = "dep_mailbox"


class Env:
    def __init__(self, client: AsyncClient, rt: Runtime) -> None:
        self.client, self.rt = client, rt

    def adapter(self, source: FakeMailSource, **hooks: Any) -> MailboxAdapter:
        assert self.rt.channels is not None
        return MailboxAdapter(self.client, source, self.rt.channels, DEP, **hooks)

    async def threads(self) -> list[dict[str, Any]]:
        assert self.rt.graph_store is not None
        async with self.rt.graph_store.engine.connect() as c:
            return [dict(r) for r in (await c.execute(graph_threads.select())).mappings()]

    async def thread_of(self, key: str) -> str:
        assert self.rt.channels is not None
        return str((await self.rt.channels.seen(DEP, [key]))[key]["thread_id"])

    async def inbox(self, thread_id: str) -> list[dict[str, Any]]:
        return (await self.client.get(f"/v1/threads/{thread_id}/inbox")).json()["data"]


@pytest.fixture
async def env() -> AsyncIterator[Env]:
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
        AsyncClient(transport=ASGITransport(app=app), base_url="http://m") as client,
    ):
        r = await client.post("/v1/deployments", json={"id": DEP, "graph": "complex_workflow", "channel": "mailbox"})
        assert r.status_code == 201, r.text
        yield Env(client, app.state.runtime)


def mid_run_hooks(env: Env) -> dict[str, Any]:
    """Holds a case's lease while a fixture message marked midRun is handled, as if its run were still going."""
    held: dict[str, str] = {}

    async def before(item: dict[str, Any]) -> None:
        if text_at(item, "_fixture", "midRun"):
            thread = await env.thread_of(references(item)[0])
            assert env.rt.leases is not None
            await env.rt.leases.acquire(thread, "run_mid")
            held["thread"] = thread

    async def after(item: dict[str, Any]) -> None:
        if (thread := held.pop("thread", None)) is not None:
            assert env.rt.leases is not None
            await env.rt.leases.release(thread, "run_mid")
            await drain(env.rt, thread)

    return {"before_item": before, "after_item": after}


async def test_full_fixture(env: Env) -> None:
    report = await env.adapter(FakeMailSource(FIXTURE), **mid_run_hooks(env)).poll()
    assert (report.items, report.new_cases, report.duplicates) == (100, 82, 10)
    assert (report.delivered, report.queued, report.removed) == (5, 3, 2)
    threads = await env.threads()
    assert len(threads) == 82 and all(t["external_key"].startswith(f"{DEP}:case-") for t in threads)
    # Mid-run replies were queued, then delivered once the case was free.
    assert [i["status"] for i in await env.inbox(await env.thread_of("case-030@mail.northfield.example"))] == [
        "delivered"
    ]
    # The graph got file ids, never attachment bytes.
    with_files = next(x for x in FIXTURE if x.get("attachments"))
    state = (await env.client.get(f"/v1/threads/{await env.thread_of(message_key(with_files))}/state")).json()["data"]
    attachments = state["values"]["email"]["attachments"]
    assert attachments and all(set(a) == {"name", "file_id"} for a in attachments)


async def test_redelivery_opens_no_second_case(env: Env) -> None:
    original = FIXTURE[0]
    again = [copy.deepcopy(original) for _ in range(3)]
    again[1]["internetMessageId"] = original["internetMessageId"].strip("<>")
    again[2]["internetMessageId"] = original["internetMessageId"].upper().replace("CASE-", "case-")
    report = await env.adapter(FakeMailSource([original, *again])).poll()
    assert (report.new_cases, report.duplicates) == (1, 3)
    assert len(await env.threads()) == 1


async def test_two_replies_in_one_poll_on_a_running_case_queue_in_order(env: Env) -> None:
    source = FakeMailSource([FIXTURE[0]])
    adapter = env.adapter(source)
    await adapter.poll()
    case = await env.thread_of(message_key(FIXTURE[0]))
    assert env.rt.leases is not None
    await env.rt.leases.acquire(case, "run_busy")
    first, second = _reply_to(FIXTURE[0], "r-1"), _reply_to(FIXTURE[0], "r-2")
    source.arrive(first, second)
    report = await adapter.poll()
    assert report.queued == 2
    assert [(i["seq"], i["messageKey"], i["status"]) for i in await env.inbox(case)] == [
        (1, "r-1@example.com", "queued"),
        (2, "r-2@example.com", "queued"),
    ]
    await env.rt.leases.release(case, "run_busy")
    assert await drain(env.rt, case) == [1, 2]
    assert [i["status"] for i in await env.inbox(case)] == ["delivered", "delivered"]


async def test_delta_lost_mid_poll_replays_without_duplicates(env: Env) -> None:
    items = [x for x in FIXTURE[:60] if "_fixture" not in x]
    source = FakeMailSource(items, page_size=20, fail_once_at=40)
    adapter = env.adapter(source)
    with pytest.raises(ConnectionError):
        await adapter.poll()
    assert env.rt.channels is not None and await env.rt.channels.cursor(DEP) is None
    report = await adapter.poll()
    unique = {message_key(x) for x in items if not references(x)}
    assert len(await env.threads()) == len(unique)
    assert report.duplicates >= 40  # the first two pages, replayed
    replies = [x for x in items if references(x)]
    for r in replies:
        case = await env.thread_of(references(r)[0])
        keys = [i["messageKey"] for i in await env.inbox(case)]
        assert len(keys) == len(set(keys))


async def test_message_without_message_id_gets_a_synthetic_key(env: Env) -> None:
    item = copy.deepcopy(FIXTURE[0])
    del item["internetMessageId"]
    report = await env.adapter(FakeMailSource([item, copy.deepcopy(item)])).poll()
    assert (report.new_cases, report.duplicates) == (1, 1)
    threads = await env.threads()
    assert len(threads) == 1 and threads[0]["external_key"].startswith(f"{DEP}:synthetic:")


async def test_paused_deployment_defers_new_cases_and_still_takes_replies(env: Env) -> None:
    source = FakeMailSource([FIXTURE[0]])
    adapter = env.adapter(source)
    await adapter.poll()
    await env.client.patch(f"/v1/deployments/{DEP}", json={"paused": True})
    source.arrive(FIXTURE[1], _reply_to(FIXTURE[0], "r-paused"))
    report = await adapter.poll()
    assert (report.new_cases, report.deferred, report.delivered) == (0, 1, 1)
    assert len(await env.threads()) == 1
    await env.client.patch(f"/v1/deployments/{DEP}", json={"paused": False})
    report = await adapter.poll()
    assert report.new_cases == 1 and len(await env.threads()) == 2


async def test_reply_on_a_finished_case_opens_a_linked_follow_up(env: Env) -> None:
    source = FakeMailSource([FIXTURE[0]])
    adapter = env.adapter(source)
    await adapter.poll()
    case = await env.thread_of(message_key(FIXTURE[0]))
    closed = await env.client.post(
        f"/reviews/{case}/decision", json={"decision": "rejected", "reason": "Not a dispute"}
    )
    assert closed.status_code == 200, closed.text
    source.arrive(_reply_to(FIXTURE[0], "r-late"))
    report = await adapter.poll()
    assert report.followups == 1
    followup = next(t for t in await env.threads() if t["parent_thread_id"] == case)
    assert followup["external_key"] == f"{DEP}:r-late@example.com"


def _reply_to(original: dict[str, Any], local: str) -> dict[str, Any]:
    return {
        "id": f"AAMk-{local}",
        "internetMessageId": f"<{local}@example.com>",
        "subject": f"Re: {original['subject']}",
        "from": original["from"],
        "receivedDateTime": "2026-10-11T11:00:00Z",
        "body": {"contentType": "text", "content": "More detail."},
        "internetMessageHeaders": [{"name": "In-Reply-To", "value": original["internetMessageId"]}],
        "attachments": [],
    }
