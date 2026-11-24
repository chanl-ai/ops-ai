"""A rule kind and a target kind added from outside run through the real routes and the real clock, and nothing in the
clock, the table or the routes names them: the clock reads a rule's own fields, or a route refuses a kind it was not
built with. The kinds are defined here and registered beside the built-ins. Each pass is one turn of the worker's
schedule loop (`keep_schedules_ticking` calls `pass_once` once a minute), run at a chosen minute."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api.routers.engine import REGISTRY
from ops_agents.api.schedule_clock import SCHEDULE_TRIGGER, ScheduleClock, Tick, WorkflowStart
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.leases import Leases
from ops_agents.store.tenancy import LOCAL_TENANT, tenant_scope
from ops_engine.store import DefinitionStore, RunStore
from ops_service_kit.settings import Settings
from ops_store.schedule import KINDS
from tests.conftest import SEED, empty_engine, started

JAMES = {"X-Dev-User": "j.richardson@harborpine.example"}
FAST = "test.trigger.fast"


class OddMinutes:
    """Every 2 minutes, on odd minutes only: 10:01, 10:03, ... 10:59, 11:01."""

    name = "odd_minutes"
    label = "Every 2 minutes, odd minutes"
    interval_field = "kind"
    schema: ClassVar[dict[str, JsonValue]] = {"type": "object", "properties": {"kind": {"const": "odd_minutes"}}}

    def check(self, raw: Any, now: datetime) -> dict[str, JsonValue]:
        return {"kind": self.name}

    def last_slot(self, rule: Any, now: datetime) -> datetime | None:
        t = now.replace(second=0, microsecond=0)
        return t if t.minute % 2 else t - timedelta(minutes=1)

    def next_slots(self, rule: Any, after: datetime, n: int) -> list[datetime]:
        t = self.last_slot(rule, after) or after
        return [t + timedelta(minutes=2 * (i + 1)) for i in range(n)]

    def words(self, rule: Any) -> str:
        return "Every 2 minutes, on odd minutes"


class Ticks:
    """A target kind that does its work by writing down the slot, and is never busy."""

    def __init__(self) -> None:
        self.slots: list[str] = []

    async def busy(self, tick: Tick) -> bool:
        return False

    async def tick(self, tick: Tick) -> str | None:
        self.slots.append(tick.slot.strftime("%H:%M"))
        return None


@pytest.fixture
def kinds() -> Iterator[None]:
    KINDS.register(OddMinutes())
    REGISTRY.register(replace(REGISTRY.get(SCHEDULE_TRIGGER, 1), id=FAST, start=None))
    yield
    KINDS._kinds.pop("odd_minutes")  # pyright: ignore[reportPrivateUsage]
    REGISTRY._types.pop((FAST, 1))  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
async def stack(database_url: str, graph_models: Any) -> AsyncIterator[tuple[AsyncClient, AsyncEngine]]:
    settings = Settings(database_url=database_url, seed_dir=SEED, schedule_floor_minutes=1)
    async with empty_engine(database_url) as engine, started(engine, settings, graph_models, checked=True) as (_, c):
        yield c, engine


def at(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"2026-11-23T{hhmm}").replace(tzinfo=UTC)


async def live(c: AsyncClient, engine: AsyncEngine, trigger: str) -> str:
    wid = f"wf_{uuid4().hex[:8]}"
    d: dict[str, Any] = {
        "schemaVersion": 2,
        "id": wid,
        "name": "Plugin",
        "nodes": [
            {"id": "start", "type": trigger, "typeVersion": 1, "name": "Sched", "parameters": {}},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }
    made = await c.post("/v1/workflows/definitions", json={"definition": d}, headers=JAMES)
    assert made.status_code < 300, made.text
    with tenant_scope(LOCAL_TENANT):
        await DefinitionStore(EngineTransactions(engine)).go_live(wid, made.json()["data"]["version"])
    return wid


async def test_a_rule_kind_and_a_target_kind_added_in_a_test_run_through_the_real_routes_and_clock(
    stack: tuple[AsyncClient, AsyncEngine], kinds: None
) -> None:
    c, engine = stack
    listed = (await c.get("/v1/schedules/kinds", headers=JAMES)).json()["data"]
    assert "odd_minutes" in [k["name"] for k in listed]
    ours = {"kind": "odd_minutes"}
    preview = (await c.post("/v1/schedules/preview", json={"rule": ours}, headers=JAMES)).json()["data"]
    assert preview["words"] == "Every 2 minutes, on odd minutes" and len(preview["nextRuns"]) == 3

    started_runs, fast = await live(c, engine, SCHEDULE_TRIGGER), await live(c, engine, FAST)
    for wid in (started_runs, fast):
        saved = await c.put(
            f"/v1/workflows/definitions/{wid}/triggers/start/schedule", json={"rule": ours}, headers=JAMES
        )
        assert saved.status_code == 200 and saved.json()["data"]["words"] == preview["words"], saved.text

    ticks = Ticks()
    runs = RunStore(EngineTransactions(engine))
    clock = ScheduleClock(
        engine,
        Leases(engine, owner="worker:a", ttl=30),
        handlers={SCHEDULE_TRIGGER: WorkflowStart(runs), FAST: ticks},
    )
    for minute in range(0, 6):
        await clock.pass_once(at(f"10:0{minute}"))
        async with engine.begin() as conn:  # a finished run, so the next tick is not skipped as busy
            await conn.execute(sa.text("UPDATE engine_runs SET status = 'succeeded'"))
    with tenant_scope(LOCAL_TENANT):
        made = await runs.list(workflow_id=started_runs)
    assert sorted(str(cast(dict[str, Any], r.input)["dueAt"])[11:16] for r in made) == ["10:01", "10:03", "10:05"]
    assert ticks.slots == ["10:01", "10:03", "10:05"]
