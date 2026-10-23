"""The runner through its queue on PostgreSQL, by failure mode: a run that runs without a worker or is lost without
one, a review decision that does not resume it, a second decision that resumes it twice, two workers on one row, a
dead worker's row never picked up again, and a pass that writes as another team than its run's."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import engine_reviews
from ops_agents.api.auth import Principal
from ops_agents.api.engine_host import RunEvents, RunReviews, ThreadLeases
from ops_agents.api.worker import engine_pass, enter_run
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.events import EventLog
from ops_agents.store.leases import Leases
from ops_agents.store.tenancy import tenant_scope
from ops_checkpointer import LeaseSupersededError
from ops_engine import default_registry
from ops_engine.definition import parse
from ops_engine.ports import Access, EnginePorts, ToolResult
from ops_engine.store import DefinitionStore, RunStore, WorkQueue
from ops_engine.worker import Worker, WorkerHost
from ops_service_kit.ids import new_id
from ops_store import isolation

# The dev caller in team_a, the team the engine tests run their workflows in: it decides only that team's reviews.
M = Principal(name="m@x", email="m@x", team_id="team_a", tenant_id="local", team_ids=("team_a",), dev=True)

BASIC = parse((Path(__file__).parents[1] / "fixtures" / "engine" / "basic.yaml").read_text())


class CountingTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.calls.append(key)
        return ToolResult(True, {"id": input.get("customer_id")})

    async def access(self, operation: str) -> Access:
        return "read"

    async def mint(self, run_id: str, call: dict[str, Any], approval: dict[str, Any]) -> str | None:
        return None

    async def find(self, key: str, operation: str) -> ToolResult | None:
        return None


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


def worker(engine: AsyncEngine, tools: CountingTools, saver: InMemorySaver, *, ttl: float = 6.0) -> Worker:
    owner = f"test-{uuid4().hex[:6]}"
    host = WorkerHost(
        tx=EngineTransactions(engine),
        registry=default_registry(),
        ports=EnginePorts(tools=tools, reviews=RunReviews()),
        leases=ThreadLeases(Leases(engine, owner=owner, ttl=ttl)),
        events=RunEvents(EventLog(engine)),
        checkpointer=saver,
        run_scope=tenant_scope,
        owner=owner,
        # Each pass in its run's team, as the service's worker does: a typed step reads its team's task types.
        enter_run=enter_run,
    )
    return Worker(host)


async def start(engine: AsyncEngine, tenant: str, payload: dict[str, Any], key: str | None = None) -> str:
    tx = EngineTransactions(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            BASIC.id, name="Refund", definition=BASIC.wire(), digest=BASIC.digest(), now="now", by="a@x", stage="live"
        )
        run_id = new_id("wfrun")
        run, _ = await RunStore(tx).create(
            {
                "id": run_id,
                "team_id": "team_a",
                "workflow_id": BASIC.id,
                "version": version,
                "digest": BASIC.digest(),
                "run_key": key or run_id,
                "mode": "live",
                "input": payload,
                "created_by": "a@x",
            }
        )
        return str(run["id"])


async def drain(w: Worker) -> int:
    n = 0
    while await w.work_once():
        n += 1
    return n


async def test_a_queued_run_waits_for_a_worker_then_reaches_its_review_and_ends_on_the_decision(
    engine: AsyncEngine,
) -> None:
    tenant, tools, saver = f"t-{uuid4().hex[:8]}", CountingTools(), InMemorySaver()
    run_id = await start(engine, tenant, {"customerId": "C-1", "amount": 250})
    runs = RunStore(EngineTransactions(engine))
    with tenant_scope(tenant):
        assert (await runs.get(run_id) or {})["status"] == "queued"
    w = worker(engine, tools, saver)
    await drain(w)
    with tenant_scope(tenant):
        run = await runs.get(run_id) or {}
        assert run["status"] == "waiting" and run["waiting"]["node"] == "review"
        rt: Any = SimpleNamespace(db=engine, settings=SimpleNamespace(lease_ttl_seconds=6.0))
        review = await engine_reviews.decide(rt, M, run_id, decision="approved", reason=None)
        assert review["status"] == "approved"
        # The same decision again is the same review; a different one is refused, and nothing is queued twice.
        await engine_reviews.decide(rt, M, run_id, decision="approved", reason=None)
        assert len([x for x in await runs.work(run_id) if x["kind"] == "resume"]) == 1
    await drain(w)
    with tenant_scope(tenant):
        run = await runs.get(run_id) or {}
        assert (run["status"], run["outcome"]) == ("succeeded", "approved")
        nodes = [s["node_id"] for s in await runs.steps(run_id) if s["status"] == "ok"]
        events = await EventLog(engine).run_events(run_id, run_id, 0)
    assert nodes == ["start", "fields", "big", "lookup", "review", "approved"]
    assert len([k for k in tools.calls if k.startswith(run_id)]) == 1
    types = [e["type"] for e in events]
    assert types[0] == "started" and "waiting_review" in types and "decided" in types and types[-1] == "finished"
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)


async def test_two_workers_never_claim_one_row(engine: AsyncEngine) -> None:
    """Two rows of a build no other test uses, claimed at once by two workers: each gets one, and not the same one."""
    tenant, build = f"t-{uuid4().hex[:8]}", f"b{uuid4().hex[:8]}"
    tx = EngineTransactions(engine)
    with tenant_scope(tenant):
        for i in range(2):
            await WorkQueue(tx, "api", 6.0, build).enqueue(f"wfrun_{uuid4().hex[:8]}", "start", f"k{i}")
    queues = [WorkQueue(tx, f"w{i}", 6.0, build) for i in range(2)]
    got = await asyncio.gather(*(q.claim() for q in queues))
    assert all(g is not None for g in got), got
    assert len({g.id for g in got if g is not None}) == 2


class SlowTools(CountingTools):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.started.set()
        await asyncio.sleep(1.5)
        return await super().call(operation, input, key, generation, token)


class LosingLeases:
    """A lease its owner loses at the first heartbeat once the pass is inside its tool call, as when another worker
    took the run over mid-step. Lost earlier, under a slow start, the pass stops before it marks the run running."""

    ttl = 0.3

    def __init__(self, started: asyncio.Event) -> None:
        self.started = started

    async def acquire(self, thread_id: str, run_id: str) -> int:
        return 1

    async def heartbeat(self, thread_id: str, run_id: str) -> bool:
        return not self.started.is_set()

    async def release(self, thread_id: str, run_id: str) -> None:
        return None


async def test_a_worker_that_lost_its_lease_stops_and_writes_no_run_status(engine: AsyncEngine) -> None:
    tenant, tools = f"t-{uuid4().hex[:8]}", SlowTools()
    run_id = await start(engine, tenant, {"customerId": "C-1", "amount": 250})
    w = worker(engine, tools, InMemorySaver())
    w.host.leases = LosingLeases(tools.started)
    w.queue.ttl = 6.0
    claimed = None
    while (got := await w.queue.claim()) is not None:
        if got.run_id == run_id:
            claimed = got
            break
    assert claimed is not None
    await w.process(claimed)
    await asyncio.sleep(1.6)  # past the tool call the pass would have finished with
    with tenant_scope(tenant):
        run = await RunStore(EngineTransactions(engine)).get(run_id) or {}
    assert run["status"] == "running", "a superseded worker must not move the run to waiting"
    assert not [k for k in tools.calls if k.startswith(run_id)], "the pass was stopped before the tool answered"


async def test_a_status_write_under_a_superseded_generation_is_refused(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    run_id = await start(engine, tenant, {"customerId": "C-1", "amount": 5})
    leases = Leases(engine, owner="a", ttl=0.2)
    old = await leases.acquire(run_id, "first")
    await asyncio.sleep(0.4)
    assert await Leases(engine, owner="b", ttl=6.0).acquire(run_id, "second") == old + 1
    runs = RunStore(EngineTransactions(engine))
    with tenant_scope(tenant), pytest.raises(LeaseSupersededError):
        await runs.update(run_id, generation=old, status="succeeded")
    with tenant_scope(tenant), pytest.raises(LeaseSupersededError):
        await EventLog(engine).append(thread_id=run_id, team_id="t", run_id=run_id, type_="finished", generation=old)


async def test_a_dead_workers_claim_lapses_and_another_worker_finishes_the_run(engine: AsyncEngine) -> None:
    tenant, tools, saver = f"t-{uuid4().hex[:8]}", CountingTools(), InMemorySaver()
    run_id = await start(engine, tenant, {"customerId": "C-1", "amount": 5})
    dead = WorkQueue(EngineTransactions(engine), "dead", 0.5)
    claimed = None
    while (w := await dead.claim()) is not None:  # earlier tests' leftovers are claimed and dropped too
        if w.run_id == run_id:
            claimed = w
            break
    assert claimed is not None and claimed.attempts == 1
    await asyncio.sleep(1.0)
    await drain(worker(engine, tools, saver))
    with tenant_scope(tenant):
        run = await RunStore(EngineTransactions(engine)).get(run_id) or {}
        work = await RunStore(EngineTransactions(engine)).work(run_id)
    assert (run["status"], run["outcome"]) == ("succeeded", "small")
    assert work[0]["attempts"] == 2 and work[0]["status"] == "done"


class DoubtfulTools(CountingTools):
    """Every write is in doubt at the gateway: its claim stays running."""

    async def access(self, operation: str) -> Access:
        return "write"

    async def find(self, key: str, operation: str) -> ToolResult | None:
        return ToolResult(False, pending=True, reason="still running")


async def test_a_write_in_doubt_past_the_retry_cap_fails_the_run(engine: AsyncEngine) -> None:
    from ops_engine.journal import StepRow  # noqa: PLC0415
    from ops_engine.store import SqlJournal  # noqa: PLC0415
    from ops_engine.store.tables import engine_work  # noqa: PLC0415
    from ops_engine.worker import MAX_DOUBT_PASSES  # noqa: PLC0415

    tenant, tools = f"t-{uuid4().hex[:8]}", DoubtfulTools()
    run_id = await start(engine, tenant, {"customerId": "C-1", "amount": 250})
    with tenant_scope(tenant):
        await SqlJournal(EngineTransactions(engine)).begin(
            StepRow(run_id, "lookup", 1, 1, "running", "write", f"{run_id}:lookup:1:1", input={})
        )
    async with engine.begin() as c:
        await c.execute(engine_work.update().where(engine_work.c.run_id == run_id).values(attempts=MAX_DOUBT_PASSES))
    w = worker(engine, tools, InMemorySaver())
    claimed = None
    while (got := await w.queue.claim()) is not None:
        if got.run_id == run_id:
            claimed = got
            break
    assert claimed is not None
    await w.process(claimed)
    with tenant_scope(tenant):
        run = await RunStore(EngineTransactions(engine)).get(run_id) or {}
    assert run["status"] == "failed" and "doubt" in str(run["error"]), run
    assert not [k for k in tools.calls if k.startswith(run_id)], "never re-sent"


class TeamTools(CountingTools):
    """Notes the team each tool call acts as: its service token names that team to tools-service."""

    def __init__(self) -> None:
        super().__init__()
        self.teams: list[str | None] = []

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.teams.append(isolation.team())
        return await super().call(operation, input, key, generation, token)


class TeamEvents(RunEvents):
    """The real event log, noting the team each append's transaction acts as."""

    def __init__(self, log_: EventLog) -> None:
        super().__init__(log_)
        self.teams: list[str | None] = []

    async def append(
        self, run_id: str, team_id: str, type_: str, node: str | None, data: Any, *, generation: int | None = None
    ) -> None:
        self.teams.append(isolation.team())
        await super().append(run_id, team_id, type_, node, data, generation=generation)


async def test_a_pass_acts_as_its_runs_team_whatever_team_the_claiming_loop_holds(engine: AsyncEngine) -> None:
    """A run of team_a claimed by a loop whose context names team_other: the pass enters team_a before its first
    event and tool call (enter_run), as the database's team policy requires of a team-owned write. Without it the pass
    acts for no team, and a worker whose transactions did not name the run's team failed its first event on the
    policy (fb-16aa519c)."""
    tenant, tools, saver = f"t-{uuid4().hex[:8]}", TeamTools(), InMemorySaver()
    run_id = await start(engine, tenant, {"customerId": "C-1", "amount": 250})
    owner = f"test-{uuid4().hex[:6]}"
    events = TeamEvents(EventLog(engine))
    host = WorkerHost(
        tx=EngineTransactions(engine),
        registry=default_registry(),
        ports=EnginePorts(tools=tools, reviews=RunReviews()),
        leases=ThreadLeases(Leases(engine, owner=owner, ttl=6.0)),
        events=events,
        checkpointer=saver,
        run_scope=engine_pass,
        owner=owner,
        enter_run=enter_run,
    )
    with isolation.scope(tenant, "team_other"):
        await drain(Worker(host))
    with tenant_scope(tenant):
        run = await RunStore(EngineTransactions(engine)).get(run_id) or {}
        written = await EventLog(engine).run_events(run_id, run_id, 0)
    assert run["status"] == "waiting"
    assert events.teams and set(events.teams) == {"team_a"}, events.teams
    assert tools.teams == ["team_a"]
    assert written and written[0]["type"] == "started"
