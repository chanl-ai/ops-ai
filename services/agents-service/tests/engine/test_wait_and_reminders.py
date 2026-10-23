"""Wait and reminders (c-277) on the real worker, on PostgreSQL, by failure mode: a Wait is woken early, or lost when
the worker restarts; a date already past waits anyway, and a value that is not a date waits for ever; a reminder
never fires, ends the review's wait, or keeps firing after the review is decided; a reminder is missing from
Activity."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api import engine_reviews
from ops_agents.api.service_events import reminders
from ops_agents.store.activity import Activity, Filters, Scope
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.service_events import service_events
from ops_agents.store.tenancy import tenant_scope, tenant_tx
from ops_engine.definition import WorkflowDefinition, parse
from ops_engine.store import DefinitionStore, RunStore
from ops_engine.store.tables import engine_work
from ops_service_kit.ids import new_id
from tests.engine.test_worker import CountingTools, M, drain, engine, worker  # noqa: F401  # pyright: ignore[reportUnusedImport]

# About a second: long enough to see it still waiting, short enough to wait out.
ONE_SECOND_HOURS = 1 / 3600


def flow(wid: str, step: dict[str, Any], ports: dict[str, str]) -> WorkflowDefinition:
    """start → `step` → one End per port, each named for its port's outcome."""
    ends = [{"id": p, "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": o}} for p, o in ports.items()]
    return parse(
        {
            "schemaVersion": 2,
            "id": wid,
            "nodes": [
                {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
                step,
                *ends,
            ],
            "connections": [
                {"from": {"node": "start", "port": "payload"}, "to": {"node": step["id"], "port": "in"}},
                *({"from": {"node": step["id"], "port": p}, "to": {"node": p, "port": "in"}} for p in ports),
            ],
        }
    )


def wait(**params: Any) -> dict[str, Any]:
    return {"id": "pause", "type": "ops.flow.wait", "typeVersion": 1, "parameters": params}


REVIEW = {
    "id": "review",
    "type": "ops.flow.humanReview",
    "typeVersion": 1,
    "parameters": {"title": "Check the levy", "remindEveryHours": ONE_SECOND_HOURS},
}


async def start(db: AsyncEngine, tenant: str, d: WorkflowDefinition) -> str:
    tx = EngineTransactions(db)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            d.id, name=d.id, definition=d.wire(), digest=d.digest(), now="now", by="a@x", stage="live"
        )
        run_id = new_id("wfrun")
        await RunStore(tx).create(
            {
                "id": run_id,
                "team_id": "team_a",
                "workflow_id": d.id,
                "version": version,
                "digest": d.digest(),
                "run_key": run_id,
                "mode": "live",
                "input": {},
                "created_by": "a@x",
            }
        )
        return run_id


async def run_of(db: AsyncEngine, tenant: str, run_id: str) -> dict[str, Any]:
    with tenant_scope(tenant):
        return await RunStore(EngineTransactions(db)).get(run_id) or {}


async def reminded(db: AsyncEngine, tenant: str, run_id: str) -> list[str]:
    """The task.reminder event keys recorded for the run, in order."""
    e = service_events
    with tenant_scope(tenant):
        async with tenant_tx(db) as c:
            q = sa.select(e.c.event_key).where(e.c.name == "task.reminder", e.c.event_key.startswith(f"{run_id}:"))
            return sorted(str(k) for k in (await c.execute(q)).scalars())


async def wakeups(db: AsyncEngine, tenant: str, run_id: str) -> int:
    """The delayed wake-ups queued for the run: one per pause for a time."""
    w = engine_work
    with tenant_scope(tenant):
        async with tenant_tx(db) as c:
            q = sa.select(sa.func.count()).where(w.c.run_id == run_id, w.c.kind == "timeout")
            return int((await c.execute(q)).scalar_one())


async def test_a_wait_holds_no_worker_and_goes_on_once_its_time_has_passed_after_a_restart(engine: AsyncEngine) -> None:  # noqa: F811
    tenant, saver = f"t-{uuid4().hex[:8]}", InMemorySaver()
    run_id = await start(engine, tenant, flow(f"w_{uuid4().hex[:6]}", wait(seconds=1.5), {"out": "done"}))
    await drain(worker(engine, CountingTools(), saver))
    assert (await run_of(engine, tenant, run_id))["status"] == "waiting"
    await drain(worker(engine, CountingTools(), saver))
    assert (await run_of(engine, tenant, run_id))["status"] == "waiting", "woken before its time"
    await asyncio.sleep(2)
    await drain(worker(engine, CountingTools(), saver))  # another worker: the first one is gone
    run = await run_of(engine, tenant, run_id)
    assert (run["status"], run["outcome"]) == ("succeeded", "done") and await wakeups(engine, tenant, run_id) == 1, run


async def test_a_past_date_goes_on_at_once_and_one_that_is_not_a_date_leaves_by_error(engine: AsyncEngine) -> None:  # noqa: F811
    tenant, saver = f"t-{uuid4().hex[:8]}", InMemorySaver()
    ports = {"out": "done", "error": "bad_date"}
    past = await start(engine, tenant, flow(f"w_{uuid4().hex[:6]}", wait(mode="until", until="2020-01-31"), ports))
    junk = await start(engine, tenant, flow(f"w_{uuid4().hex[:6]}", wait(mode="until", until="soon"), ports))
    await drain(worker(engine, CountingTools(), saver))
    assert (await run_of(engine, tenant, past))["outcome"] == "done"
    assert await wakeups(engine, tenant, past) == 0, "a past date paused instead of going on"
    assert (await run_of(engine, tenant, junk))["outcome"] == "bad_date"


async def test_a_reminder_repeats_while_the_review_waits_and_stops_once_it_is_decided(engine: AsyncEngine) -> None:  # noqa: F811
    tenant, saver = f"t-{uuid4().hex[:8]}", InMemorySaver()
    run_id = await start(engine, tenant, flow(f"r_{uuid4().hex[:6]}", REVIEW, {"approve": "ok", "reject": "no"}))
    w = worker(engine, CountingTools(), saver)
    w.host.remind = reminders(engine)
    await drain(w)
    for n in (1, 2):
        await asyncio.sleep(1.2)
        await drain(w)
        assert await reminded(engine, tenant, run_id) == [f"{run_id}:review:1:{i}" for i in range(1, n + 1)]
        assert (await run_of(engine, tenant, run_id))["status"] == "waiting", "a reminder never ends the wait"
    with tenant_scope(tenant):
        rows = await Activity(engine).page(
            Scope(teams={"reminder": ("team_a",)}, owner="m@x"), Filters(), page=1, page_size=10
        )
    assert [(r["kind"], r["status"], r["ref_id"]) for r in rows.rows] == [("reminder", "waiting", run_id)] * 2
    assert rows.rows[0]["title"].startswith("Reminder: Check the levy, waiting "), rows.rows[0]["title"]
    rt: Any = SimpleNamespace(db=engine, settings=SimpleNamespace(lease_ttl_seconds=6.0))
    with tenant_scope(tenant):
        await engine_reviews.decide(rt, M, run_id, decision="approved", reason=None)
    await drain(w)
    await asyncio.sleep(1.2)
    await drain(w)
    assert len(await reminded(engine, tenant, run_id)) == 2, "reminded after the decision"
    assert (await run_of(engine, tenant, run_id))["outcome"] == "ok"
