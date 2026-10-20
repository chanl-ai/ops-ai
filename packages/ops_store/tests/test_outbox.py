"""The service event outbox (c-258), by failure mode: an event written in a transaction that rolls back is sent
anyway; one the receiver refuses while it is down is dropped instead of retried; a failing event holds back the ones
behind it; an event is sent again after it was delivered; two relays deliver the same event at once."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_service_kit.settings import Settings
from ops_store.outbox import Relay, add, outbox_table


class Receiver:
    """agents-service's POST /v1/events as the relay sees it: down until told otherwise, then recording each body."""

    def __init__(self) -> None:
        self.up = False
        self.got: list[dict[str, Any]] = []
        self.refuse: set[str] = set()

    async def __call__(self, event: dict[str, Any]) -> None:
        if not self.up:
            raise ConnectionError("agents-service is down")
        if event["body"]["key"] in self.refuse:
            raise ValueError("422 payload_too_large")
        self.got.append(event)


@pytest.fixture
async def setup() -> AsyncIterator[tuple[AsyncEngine, sa.Table]]:
    url = Settings().database_url
    if not url.startswith("postgresql"):
        pytest.skip("the outbox is proven on PostgreSQL, where relays run concurrently")
    engine = create_async_engine(url)
    table = outbox_table(sa.MetaData(), f"outbox_test_{uuid4().hex[:8]}")
    async with engine.begin() as c:
        await c.run_sync(table.create)
    yield engine, table
    async with engine.begin() as c:
        await c.run_sync(table.drop)
    await engine.dispose()


async def emit(engine: AsyncEngine, table: sa.Table, key: str, *, now: float = 0.0, commit: bool = True) -> None:
    async with engine.connect() as c:
        tx = await c.begin()
        await add(c, table, tenant_id="acme", team_id="team_ops", name="file.deleted", key=key, payload={}, now=now)
        await (tx.commit() if commit else tx.rollback())


async def test_an_event_commits_with_its_change_and_waits_out_an_outage(setup: tuple[AsyncEngine, sa.Table]) -> None:
    engine, table = setup
    clock = [10.0]
    receiver = Receiver()
    relay = Relay(engine, table, receiver, clock=lambda: clock[0])
    await emit(engine, table, "kept", now=1.0)
    await emit(engine, table, "rolled_back", now=1.0, commit=False)
    assert await relay.once() == 0, "nothing is delivered while agents-service is down"
    receiver.up = True
    assert await relay.once() == 0, "a failed event waits out its backoff"
    clock[0] += 3
    assert await relay.once() == 1
    assert [e["body"]["key"] for e in receiver.got] == ["kept"], "a rolled-back change reported nothing"
    clock[0] += 120
    assert await relay.once() == 0 and len(receiver.got) == 1, "a delivered event is never sent again"


async def test_a_refused_event_holds_no_other_back(setup: tuple[AsyncEngine, sa.Table]) -> None:
    engine, table = setup
    receiver = Receiver()
    receiver.up, receiver.refuse = True, {"bad"}
    for key in ("bad", "good"):
        await emit(engine, table, key)
    assert await Relay(engine, table, receiver, clock=lambda: 5.0).once() == 1
    async with engine.connect() as c:
        bad = (await c.execute(sa.select(table).where(table.c.event_key == "bad"))).mappings().one()
    assert bad["sent_at"] is None and bad["attempts"] == 1 and "payload_too_large" in bad["last_error"], bad


async def test_two_relays_deliver_each_event_once(setup: tuple[AsyncEngine, sa.Table]) -> None:
    engine, table = setup
    receiver = Receiver()
    receiver.up = True
    for n in range(30):
        await emit(engine, table, f"k{n}")

    async def slow(event: dict[str, Any]) -> None:
        await asyncio.sleep(0.01)
        await receiver(event)

    relays = [Relay(engine, table, slow, batch=10, clock=lambda: 5.0) for _ in range(2)]
    while sum(await asyncio.gather(*(r.once() for r in relays))):
        pass
    keys = [e["body"]["key"] for e in receiver.got]
    assert sorted(keys) == sorted(f"k{n}" for n in range(30)) and len(keys) == len(set(keys)), keys


async def test_old_delivered_and_never_sent_events_are_pruned_and_one_being_retried_is_kept(
    setup: tuple[AsyncEngine, sa.Table],
) -> None:
    """The outbox only grew: every delivered event and every one replaced before it was due stayed for good."""
    engine, table = setup
    week = 7 * 86400.0
    for key in ("old-sent", "new-sent", "old-replaced", "old-retrying"):
        await emit(engine, table, key, now=0.0 if key.startswith("old") else week)
    marks = {
        "old-sent": {"sent_at": 1.0, "next_at": None},
        "new-sent": {"sent_at": week, "next_at": None},
        "old-replaced": {"next_at": None, "last_error": "superseded by a newer correction"},
        "old-retrying": {"next_at": week + 60, "attempts": 9},
    }
    async with engine.begin() as c:
        for key, values in marks.items():
            await c.execute(table.update().where(table.c.event_key == key).values(**values))
    assert await Relay(engine, table, Receiver(), clock=lambda: week + 10).prune() == 2
    async with engine.connect() as c:
        left = sorted(r.event_key for r in await c.execute(sa.select(table.c.event_key)))
    assert left == ["new-sent", "old-retrying"], left
