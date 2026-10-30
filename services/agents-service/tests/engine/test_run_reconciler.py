"""The run reconciler (c-561) on PostgreSQL, by failure mode: a run with nothing behind it reads Running or Queued for
ever; a healthy run is marked Stuck because it waits on a person, an event, its children or a timer, or holds a live
claim; a run whose worker keeps dying on it flips between Running and Queued; a run queued under an older engine build
is never claimed; and a child that runs past its time limit keeps its parent waiting."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.sweeper import reconcile_runs
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore, WorkQueue
from ops_engine.store.tables import engine_runs, engine_steps, engine_work
from tests.engine.test_worker import start


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


def ago(minutes: float) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat(timespec="milliseconds")


async def setup(
    engine: AsyncEngine,
    tenant: str,
    *,
    status: str,
    quiet_minutes: float = 11,
    work: str | None = None,
    waiting: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> str:
    """A run in `status`, unchanged for `quiet_minutes`, with `work` naming its one work row: None (none left),
    "later" (queued, due in 2 h), "claimed" (a live claim), "lapsed" (reclaimed 6 times after its worker died), or
    "old-build" (queued for another engine build)."""
    run_id = await start(engine, tenant, {"customerId": "C-1", "amount": 5})
    w, r = engine_work, engine_runs
    async with engine.begin() as c:
        values: dict[str, Any] = {"status": status, "updated_at": ago(quiet_minutes), "waiting": waiting}
        if created_by:
            values["created_by"] = created_by
        await c.execute(r.update().where(r.c.id == run_id).values(**values))
        mine = w.c.run_id == run_id
        if work is None:
            await c.execute(w.update().where(mine).values(status="done"))
        elif work == "later":
            await c.execute(w.update().where(mine).values(status="queued", available_at=time.time() + 7200))
        elif work == "claimed":
            alive = {"status": "claimed", "claimed_by": "w-live", "lease_expires_at": time.time() + 15}
            await c.execute(w.update().where(mine).values(**alive))
        elif work == "lapsed":
            await c.execute(w.update().where(mine).values(status="queued", lapses=6))
        elif work == "old-build":
            await c.execute(w.update().where(mine).values(status="queued", build="0"))
    return run_id


async def status_of(engine: AsyncEngine, tenant: str, run_id: str) -> dict[str, Any]:
    with tenant_scope(tenant):
        return await RunStore(EngineTransactions(engine)).get(run_id) or {}


async def test_a_run_with_nothing_behind_it_is_stuck_with_the_reason(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    queued = await setup(engine, tenant, status="queued")
    running = await setup(engine, tenant, status="running")
    await reconcile_runs(EngineTransactions(engine))
    for run_id in (queued, running):
        run = await status_of(engine, tenant, run_id)
        assert run["status"] == "stuck" and "Nothing is working on this run" in str(run["error"]), run


async def test_runs_something_is_behind_are_left_alone(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    left = {
        "recent": await setup(engine, tenant, status="queued", quiet_minutes=2),
        "due later": await setup(engine, tenant, status="queued", work="later"),
        "live claim": await setup(engine, tenant, status="running", work="claimed"),
        "review": await setup(
            engine, tenant, status="waiting", waiting={"node": "review", "payload": {"kind": "review"}}
        ),
        "event": await setup(
            engine, tenant, status="waiting", work="later", waiting={"node": "wait", "payload": {"kind": "external"}}
        ),
    }
    parent = await setup(engine, tenant, status="waiting", waiting={"node": "kids", "payload": {"kind": "children"}})
    left["children"] = parent
    await setup(engine, tenant, status="running", quiet_minutes=1, work="claimed", created_by=f"run:{parent}")
    await reconcile_runs(EngineTransactions(engine))
    for why, run_id in left.items():
        assert (await status_of(engine, tenant, run_id))["status"] != "stuck", why


async def test_a_parent_whose_children_all_ended_without_waking_it_is_stuck(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    parent = await setup(engine, tenant, status="waiting", waiting={"node": "kids", "payload": {"kind": "children"}})
    await setup(engine, tenant, status="succeeded", created_by=f"run:{parent}")
    await reconcile_runs(EngineTransactions(engine))
    run = await status_of(engine, tenant, parent)
    assert run["status"] == "stuck" and "nothing that can still wake it" in str(run["error"]), run


async def test_a_run_whose_worker_keeps_dying_is_stuck_and_no_longer_claimed(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    run_id = await setup(engine, tenant, status="running", quiet_minutes=1, work="lapsed")
    await reconcile_runs(EngineTransactions(engine))
    run = await status_of(engine, tenant, run_id)
    assert run["status"] == "stuck" and "stopped 6 times" in str(run["error"]), run
    async with engine.connect() as c:
        rows = (await c.execute(sa.select(engine_work.c.status).where(engine_work.c.run_id == run_id))).scalars()
        assert list(rows) == ["stuck"]


async def died_on_its_last_claim(engine: AsyncEngine, run_id: str, *, alive: bool = False) -> None:
    """The 7th claim of the run's work row, after 6 lapsed reclaims: its worker died too (or, `alive`, still runs)."""
    lease = time.time() + (15 if alive else -5)
    async with engine.begin() as c:
        await c.execute(
            engine_work.update()
            .where(engine_work.c.run_id == run_id)
            .values(status="claimed", claimed_by="w-gone", lease_expires_at=lease, lapses=6)
        )


async def recorded(engine: AsyncEngine, tenant: str, run_id: str, node: str, *, finished: bool) -> None:
    async with engine.begin() as c:
        await c.execute(
            engine_steps.insert().values(
                run_id=run_id,
                node_id=node,
                iteration=1,
                attempt=1,
                tenant_id=tenant,
                status="ok" if finished else "running",
                effects="read",
                key=f"{run_id}:{node}:1",
                started_at=ago(3),
                finished_at=ago(2) if finished else None,
                node_type="ops.tool.call",
                port="ok" if finished else None,
            )
        )


async def test_a_worker_that_died_on_its_last_claim_is_counted_and_the_step_named(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    after = await setup(engine, tenant, status="running", quiet_minutes=1)
    await died_on_its_last_claim(engine, after)
    await recorded(engine, tenant, after, "lookup", finished=True)
    during = await setup(engine, tenant, status="running", quiet_minutes=1)
    await died_on_its_last_claim(engine, during)
    await recorded(engine, tenant, during, "lookup", finished=False)
    await reconcile_runs(EngineTransactions(engine))
    assert (await status_of(engine, tenant, after))["error"] == "Its worker stopped 7 times after Look up the customer."
    assert (await status_of(engine, tenant, during))["error"] == (
        "Its worker stopped 7 times while running Look up the customer."
    )


async def test_a_live_last_claim_is_left_to_its_worker(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    run_id = await setup(engine, tenant, status="running", quiet_minutes=1)
    await died_on_its_last_claim(engine, run_id, alive=True)
    await reconcile_runs(EngineTransactions(engine))
    assert (await status_of(engine, tenant, run_id))["status"] == "running"


async def ended_graph(engine: AsyncEngine, run_id: str, *, status: str, error: str | None = None) -> None:
    """The run's own graph reached an End (its outcome is set) while runs it started may still be going."""
    async with engine.begin() as c:
        await c.execute(
            engine_runs.update()
            .where(engine_runs.c.id == run_id)
            .values(status=status, outcome="replied", waiting=None, error=error)
        )


async def test_a_run_whose_graph_ended_waits_for_the_runs_it_started_and_is_not_stuck(engine: AsyncEngine) -> None:
    """#14 staging: a run that ended at Replied while the runs it started still waited on people read Stuck, "waits for
    nothing that can still wake it", beside its own Result and "finished: Replied"."""
    tenant = f"t-{uuid4().hex[:8]}"
    parent = await setup(engine, tenant, status="waiting")
    await ended_graph(engine, parent, status="waiting")
    await setup(engine, tenant, status="waiting", work="later", created_by=f"run:{parent}",
                waiting={"node": "review", "payload": {"kind": "review"}})  # fmt: skip
    await reconcile_runs(EngineTransactions(engine))
    assert (await status_of(engine, tenant, parent))["status"] == "waiting"


async def test_a_run_whose_graph_ended_and_whose_runs_all_ended_succeeds(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    parent = await setup(engine, tenant, status="running")
    await ended_graph(engine, parent, status="running")
    await setup(engine, tenant, status="succeeded", created_by=f"run:{parent}")
    await reconcile_runs(EngineTransactions(engine))
    run = await status_of(engine, tenant, parent)
    assert run["status"] == "succeeded" and run["finished_at"] is not None, run


async def test_a_run_wrongly_marked_stuck_while_its_runs_wait_goes_back_to_waiting(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    parent = await setup(engine, tenant, status="stuck")
    await ended_graph(engine, parent, status="stuck", error="It waits for nothing that can still wake it.")
    await setup(engine, tenant, status="waiting", work="later", created_by=f"run:{parent}",
                waiting={"node": "review", "payload": {"kind": "review"}})  # fmt: skip
    await reconcile_runs(EngineTransactions(engine))
    run = await status_of(engine, tenant, parent)
    assert (run["status"], run["error"]) == ("waiting", None), run


async def test_a_run_queued_for_an_older_engine_is_stuck(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    run_id = await setup(engine, tenant, status="queued", quiet_minutes=1, work="old-build")
    await reconcile_runs(EngineTransactions(engine))
    run = await status_of(engine, tenant, run_id)
    assert run["status"] == "stuck" and "older version" in str(run["error"]), run


async def test_a_lapsed_claim_counts_and_a_busy_release_does_not(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    run_id = await start(engine, tenant, {"customerId": "C-1", "amount": 5})
    tx = EngineTransactions(engine)

    async def claim(owner: str, ttl: float) -> Any:
        q = WorkQueue(tx, owner, ttl)
        while (got := await q.claim()) is not None:
            if got.run_id == run_id:
                return q, got
        raise AssertionError("the run's row was not claimed")

    queue, first = await claim("dying", 0.2)
    with tenant_scope(tenant):
        await queue.release(first, 0.0)  # a busy lease: given back, not lost
    _, again = await claim("dying", 0.2)
    time.sleep(0.4)  # its worker died: the claim lapses
    await claim("next", 6.0)
    async with engine.connect() as c:
        lapses = await c.scalar(sa.select(engine_work.c.lapses).where(engine_work.c.run_id == run_id))
    assert lapses == 1 and again.attempts == 2


async def test_a_child_running_past_its_time_limit_fails_and_its_parent_leaves_by_timeout(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    waits = {"node": "kids", "iteration": 1, "payload": {"kind": "children", "node": "kids", "iteration": 1}}
    parent = await setup(engine, tenant, status="waiting", waiting=waits)
    child = await setup(engine, tenant, status="running", quiet_minutes=1, work="claimed", created_by=f"run:{parent}")
    # 25 hours of steps that ran, and a day it waited for a person, which never counts.
    async with engine.begin() as c:
        for i, (began, ended, status) in enumerate(
            [(ago(60 * 50), ago(60 * 25), "ok"), (ago(60 * 25), ago(60 * 1), "waiting"), (ago(1), None, "running")]
        ):
            await c.execute(
                engine_steps.insert().values(
                    run_id=child,
                    tenant_id=tenant,
                    node_id=f"s{i}",
                    iteration=1,
                    attempt=1,
                    status=status,
                    effects="none",
                    key=f"{child}:s{i}:1:1",
                    started_at=began,
                    finished_at=ended,
                )
            )
    await reconcile_runs(EngineTransactions(engine))
    run = await status_of(engine, tenant, child)
    assert run["status"] == "failed" and "ran past its time limit" in str(run["error"]), run
    async with engine.connect() as c:
        woken = (
            await c.execute(
                sa.select(engine_work.c.kind, engine_work.c.payload).where(
                    engine_work.c.run_id == parent, engine_work.c.kind == "timeout"
                )
            )
        ).all()
    assert [w.payload["resume"] for w in woken] == [{"timeout": True}], woken


async def test_one_run_with_an_unreadable_time_does_not_stop_the_others(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    broken = await setup(engine, tenant, status="queued")
    async with engine.begin() as c:
        await c.execute(engine_runs.update().where(engine_runs.c.id == broken).values(updated_at="now"))
    other = await setup(engine, tenant, status="queued")
    await reconcile_runs(EngineTransactions(engine))
    assert (await status_of(engine, tenant, other))["status"] == "stuck"
    assert (await status_of(engine, tenant, broken))["status"] == "queued", "left for a person, not judged"


async def test_retrying_a_stuck_run_never_sends_a_recorded_write_again(engine: AsyncEngine) -> None:
    from langgraph.checkpoint.memory import InMemorySaver  # noqa: PLC0415

    from ops_engine.journal import StepRow  # noqa: PLC0415
    from ops_engine.ports import Access, ToolResult  # noqa: PLC0415
    from ops_engine.store import SqlJournal  # noqa: PLC0415
    from tests.engine.test_worker import CountingTools, drain, worker  # noqa: PLC0415

    class SentTools(CountingTools):
        """The write reached the gateway and ran there before its worker died."""

        async def access(self, operation: str) -> Access:
            return "write"

        async def find(self, key: str, operation: str) -> ToolResult | None:
            return ToolResult(True, {"reconciled": True})

    tenant, tools = f"t-{uuid4().hex[:8]}", SentTools()
    run_id = await setup(engine, tenant, status="stuck", quiet_minutes=1)
    with tenant_scope(tenant):
        await SqlJournal(EngineTransactions(engine)).begin(
            StepRow(run_id, "lookup", 1, 1, "running", "write", f"{run_id}:lookup:1:1", input={})
        )
        await RunStore(EngineTransactions(engine)).retry(run_id)
    await drain(worker(engine, tools, InMemorySaver()))
    assert not [k for k in tools.calls if k.startswith(run_id)], "a write with a record is never sent again"
    assert (await status_of(engine, tenant, run_id))["status"] in ("waiting", "succeeded"), "the run went on"


async def test_a_run_that_killed_its_worker_too_often_is_not_claimed_again(engine: AsyncEngine) -> None:
    # Between the reconciler's passes a fresh worker took the run again and died on it again.
    tenant = f"t-{uuid4().hex[:8]}"
    run_id = await setup(engine, tenant, status="running", quiet_minutes=1, work="lapsed")
    async with engine.begin() as c:
        dead = {"status": "claimed", "claimed_by": "w-dead", "lease_expires_at": time.time() - 5}
        await c.execute(engine_work.update().where(engine_work.c.run_id == run_id).values(**dead))
    queue = WorkQueue(EngineTransactions(engine), "fresh", 6.0)
    while (got := await queue.claim()) is not None:
        assert got.run_id != run_id, "a run past its lapse limit was claimed again"
