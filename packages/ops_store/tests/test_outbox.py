"""The service event outbox, by failure mode: an event written in a transaction that rolls back is sent
anyway; one the receiver refuses while it is down is dropped instead of retried; a failing event holds back the ones
behind it; an event is sent again after it was delivered; two relays deliver the same event at once; an event that
always fails is retried forever; a send holds the event's row lock while it waits on the receiver."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_service_kit.settings import Settings
from ops_store.outbox import MAX_ATTEMPTS, Relay, add, outbox_table, relay


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


class Service:
    """Another service's client as `relay()` uses it: records each post, answers with `answer`, raises while down."""

    def __init__(self, *, up: bool = True, answer: Any = None) -> None:
        self.up, self.answer = up, answer
        self.posts: list[tuple[str, dict[str, Any], str, str]] = []

    async def post(self, path: str, body: Any, /, *, tenant: str, team: str) -> Any:
        if not self.up:
            raise ConnectionError("503 from the subscriber")
        self.posts.append((path, body, tenant, team))
        return self.answer


async def emit_named(engine: AsyncEngine, table: sa.Table, name: str, key: str) -> None:
    async with engine.begin() as c:
        await add(c, table, tenant_id="acme", team_id="team_ops", name=name, key=key, payload={}, now=0.0)


async def unsent(engine: AsyncEngine, table: sa.Table) -> list[str]:
    async with engine.connect() as c:
        return list((await c.execute(sa.select(table.c.event_key).where(table.c.sent_at.is_(None)))).scalars())


async def test_each_event_goes_to_the_services_its_route_names_and_no_others(
    setup: tuple[AsyncEngine, sa.Table],
) -> None:
    """An event with its own row ignores "*"; a service this install does not run is skipped; an event with no
    route is delivered by doing nothing, so it does not wait in the outbox for ever."""
    engine, table = setup
    agents, tools = Service(), Service()
    await emit_named(engine, table, "member.removed", "m1")
    await emit_named(engine, table, "file.deleted", "f1")
    routed = relay(
        engine,
        table,
        routes={"member.removed": ("tools", "kb"), "*": ("agents",)},
        targets={"agents": agents, "tools": tools},
        role=None,
        path_by_target={"tools": "/v1/platform-events"},
    )
    assert await routed.once() == 2
    assert [(path, body["key"], tenant, team) for path, body, tenant, team in tools.posts] == [
        ("/v1/platform-events", "m1", "acme", "team_ops")
    ]
    assert [(path, body["key"]) for path, body, _, _ in agents.posts] == [("/v1/events", "f1")]

    await emit_named(engine, table, "file.deleted", "f2")
    nobody = relay(engine, table, routes={"member.removed": ("tools",)}, targets={"tools": tools}, role=None)
    assert await nobody.once() == 1 and len(tools.posts) == 1
    assert await unsent(engine, table) == []


async def test_an_event_one_of_its_services_refused_stays_unsent_and_goes_to_all_again(
    setup: tuple[AsyncEngine, sa.Table],
) -> None:
    engine, table = setup
    tools, agents = Service(), Service(up=False)
    await emit_named(engine, table, "team.created", "t1")
    clock = [5.0]
    both = relay(
        engine,
        table,
        routes={"team.created": ("tools", "agents")},
        targets={"tools": tools, "agents": agents},
        role=None,
    )
    both.clock = lambda: clock[0]
    assert await both.once() == 0
    assert await unsent(engine, table) == ["t1"], "a half-delivered event was marked sent; agents never hears it"
    agents.up = True
    clock[0] += 60.0
    assert await both.once() == 1
    assert len(agents.posts) == 1 and len(tools.posts) == 2


async def test_a_service_that_takes_the_team_from_the_token_gets_no_team_in_the_body(
    setup: tuple[AsyncEngine, sa.Table],
) -> None:
    engine, table = setup
    platform, agents = Service(), Service()
    await emit_named(engine, table, "kb.audit", "a1")
    audit = relay(
        engine,
        table,
        routes={"kb.audit": ("platform", "agents")},
        targets={"platform": platform, "agents": agents},
        role=None,
        team_in_token=frozenset({"platform"}),
    )
    assert await audit.once() == 1
    (_, to_platform, _, team), (_, to_agents, _, _) = platform.posts[0], agents.posts[0]
    assert "teamId" not in to_platform and team == "team_ops"
    assert to_agents["teamId"] == "team_ops", "the next service's body lost its team too"


async def test_enrich_gets_the_answer_of_each_delivery_and_its_failure_keeps_the_event(
    setup: tuple[AsyncEngine, sa.Table],
) -> None:
    engine, table = setup
    agents = Service(answer={"status": "started", "runIds": ["run_1"]})
    await emit_named(engine, table, "file.read_requested", "r1")
    seen: list[tuple[str, str, Any]] = []
    broken = [True]

    async def record(body: dict[str, Any], service: str, answer: Any) -> None:
        if broken[0]:
            raise RuntimeError("the read request's row could not be written")
        seen.append((body["key"], service, answer))

    clock = [5.0]
    enriched = relay(
        engine,
        table,
        routes={"*": ("agents",)},
        targets={"agents": agents},
        role=None,
        enrich=record,
    )
    enriched.clock = lambda: clock[0]
    assert await enriched.once() == 0 and await unsent(engine, table) == ["r1"]
    broken[0] = False
    clock[0] += 60.0
    assert await enriched.once() == 1
    assert seen == [("r1", "agents", {"status": "started", "runIds": ["run_1"]})]


async def test_an_event_that_always_fails_becomes_a_dead_letter_and_is_sent_again_on_redrive(
    setup: tuple[AsyncEngine, sa.Table],
) -> None:
    engine, table = setup
    clock = [10.0]
    receiver = Receiver()
    r = Relay(engine, table, receiver, clock=lambda: clock[0])
    await emit(engine, table, "doomed", now=1.0)
    for _ in range(MAX_ATTEMPTS + 5):
        await r.once()
        clock[0] += 120  # past any backoff
    async with engine.connect() as c:
        row = (await c.execute(sa.select(table.c.attempts, table.c.next_at, table.c.last_error))).one()
    assert (row.attempts, row.next_at) == (MAX_ATTEMPTS, None) and "down" in str(row.last_error), row
    assert await r.waiting() == 0 and await r.prune(keep_s=0) == 0, "a dead letter is kept, not waiting"
    receiver.up = True
    assert await r.redrive() == 1 and await r.once() == 1


async def test_a_send_holds_no_lock_on_its_event_while_the_receiver_answers(
    setup: tuple[AsyncEngine, sa.Table],
) -> None:
    engine, table = setup
    await emit(engine, table, "slow")
    locked: list[bool] = []

    async def slow(event: dict[str, Any]) -> None:
        # Another transaction asks for the row's lock without waiting while the send is under way.
        async with engine.connect() as c, c.begin():
            try:
                await c.execute(sa.select(table.c.id).with_for_update(nowait=True))
                locked.append(False)
            except DBAPIError:
                locked.append(True)

    assert await Relay(engine, table, slow).once() == 1
    assert locked == [False], "the send ran while its row was locked"
