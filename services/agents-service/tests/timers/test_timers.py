"""SLA timers on a human step: one test per way a timer could fire wrongly, twice, or never."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.api import timers as timers_module
from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.api.sweeper import sweep_once
from ops_agents.api.timers import TimerPoller
from ops_service_kit.settings import Settings
from tests.conftest import FakeGraphModels, decide, fixture_knowledge, last_run, scripted_model, sse_events

ROOT = Path(__file__).parents[2]
SEED = ROOT / "tests" / "fixtures" / "seed"
EMAIL: dict[str, Any] = json.loads((SEED / "dispute_emails.json").read_text())[0]
LEASE_TTL = 1.0


def workflow(**human: Any) -> dict[str, Any]:
    """The smallest workflow with an SLA'd human step: review, then send or close on the decision."""
    return {
        "entry": "human",
        "nodes": [
            {"id": "human", "kind": "human", "config": {"group": "tier1", **human}},
            {
                "id": "decide",
                "kind": "condition",
                "config": {"rule": "decision", "approved": "done", "rejected": "close"},
            },
            {"id": "done", "kind": "end", "config": {"status": "replied"}},
            {"id": "close", "kind": "end", "config": {"status": "closed"}},
        ],
        "edges": [{"source": "human", "target": "decide"}],
    }


@dataclass
class Rig:
    client: httpx.AsyncClient
    app: FastAPI

    @property
    def rt(self) -> Runtime:
        return self.app.state.runtime

    def poller(self, after_accept: Callable[[], Awaitable[None]] | None = None) -> TimerPoller:
        return TimerPoller(self.rt, after_accept=after_accept)  # type: ignore[arg-type]

    async def start(self, name: str, **human: Any) -> str:
        r = await self.client.post(f"/v1/graphs/{name}/versions", json={"definition": workflow(**human)})
        assert r.status_code == 201, r.text
        tid = str(
            (await self.client.post("/v1/threads", json={"graph": name, "metadata": {}})).json()["data"]["threadId"]
        )
        events = await self.run(tid, {"input": {"email": EMAIL}})
        assert events[-1]["data"]["status"] == "interrupted", events[-2:]
        return tid

    async def run(self, tid: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        res = await self.client.post(f"/v1/threads/{tid}/runs/stream", json=body)
        assert res.status_code == 200, res.text
        return sse_events(res.text)

    async def state(self, tid: str) -> dict[str, Any]:
        return (await self.client.get(f"/v1/threads/{tid}/state")).json()["data"]

    async def timers(self, tid: str) -> dict[str, str]:
        return {t["timerId"]: t["state"] for t in (await self.state(tid))["sla"]["timers"]}

    async def events(self, tid: str) -> list[str]:
        return [e["event"] for e in (await self.state(tid))["sla"]["events"]]


@pytest.fixture(scope="module")
def migrated() -> str:
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    return Settings().database_url


@pytest.fixture
async def rig(migrated: str) -> AsyncIterator[Rig]:
    settings = Settings(seed_dir=SEED, timer_poll_seconds=0, sweep_interval_seconds=3600, lease_ttl_seconds=LEASE_TTL)
    engine = create_async_engine(migrated)
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield Rig(client, app)


def sla(state: dict[str, Any]) -> dict[str, Any]:
    return state["interrupt"]["payload"]["sla"]


async def test_breach_warns_then_escalates(rig: Rig) -> None:
    tid = await rig.start("sla_escalate", sla="2s", warnAt="1s", onTimeout="escalate", escalateTo="supervisors")
    assert await rig.poller().poll_once() == []
    await asyncio.sleep(1.1)
    assert [t.split(":")[-2] for t in await rig.poller().poll_once()] == ["warn"]
    await asyncio.sleep(1.0)
    assert [t.split(":")[-2] for t in await rig.poller().poll_once()] == ["breach"]
    s = await rig.state(tid)
    assert sla(s)["group"] == "supervisors" and sla(s)["escalated"] is True
    assert await rig.events(tid) == ["sla.warn", "sla.breach", "sla.escalated"]
    # An escalated review has no breach of its own: nothing open is left to fire.
    assert "open" not in (await rig.timers(tid)).values()


async def test_decision_before_the_sla_cancels_its_timers(rig: Rig) -> None:
    tid = await rig.start("sla_decided", sla="1s", warnAt="1s", onTimeout="escalate", escalateTo="supervisors")
    await decide(rig.client, tid)
    assert (await last_run(rig.client, tid))["status"] == "done"
    assert set((await rig.timers(tid)).values()) == {"cancelled"}
    await asyncio.sleep(1.2)
    assert await rig.poller().poll_once() == []
    assert (await rig.state(tid))["values"]["status"] == "replied"


async def test_reassign_moves_the_review_and_restarts_its_clock(rig: Rig) -> None:
    tid = await rig.start("sla_reassign", sla="1s", onTimeout="reassign", reassignTo="tier2")
    await asyncio.sleep(1.1)
    assert len(await rig.poller().poll_once()) == 1
    s = await rig.state(tid)
    assert sla(s)["group"] == "tier2" and sla(s)["round"] == 1
    timers = await rig.timers(tid)
    assert sorted(timers.values()) == ["fired", "open"]
    open_due = next(t["dueAt"] for t in s["sla"]["timers"] if t["state"] == "open")
    fired_due = next(t["dueAt"] for t in s["sla"]["timers"] if t["state"] == "fired")
    assert open_due > fired_due
    assert await rig.events(tid) == ["sla.breach", "sla.reassigned"]


async def test_reject_on_timeout_closes_the_review(rig: Rig) -> None:
    tid = await rig.start("sla_reject", sla="1s", onTimeout="reject")
    await asyncio.sleep(1.1)
    assert len(await rig.poller().poll_once()) == 1
    s = await rig.state(tid)
    assert s["values"]["status"] == "closed"
    assert s["values"]["decision"]["timedOut"] is True


async def test_max_wait_rejects_after_escalation(rig: Rig) -> None:
    tid = await rig.start(
        "sla_max_wait", sla="1s", onTimeout="escalate", escalateTo="supervisors", maxWaitDays=2.5 / 86400
    )
    await asyncio.sleep(1.1)
    assert len(await rig.poller().poll_once()) == 1
    assert sla(await rig.state(tid))["escalated"] is True
    await asyncio.sleep(1.5)
    assert [t.split(":")[-2] for t in await rig.poller().poll_once()] == ["maxWait"]
    s = await rig.state(tid)
    assert s["values"]["status"] == "closed"
    assert await rig.events(tid) == ["sla.breach", "sla.escalated", "sla.max_wait"]


async def test_two_pollers_fire_a_timer_once(rig: Rig) -> None:
    tid = await rig.start("sla_two_pollers", sla="1s", onTimeout="escalate", escalateTo="supervisors")
    await asyncio.sleep(1.1)
    a, b = await asyncio.gather(rig.poller().poll_once(), rig.poller().poll_once())
    assert len(a) + len(b) == 1
    assert sla(await rig.state(tid))["round"] == 1
    assert await rig.events(tid) == ["sla.breach", "sla.escalated"]


async def test_timer_waits_while_the_thread_is_running(rig: Rig) -> None:
    tid = await rig.start("sla_multitask", sla="1s", onTimeout="escalate", escalateTo="supervisors")
    await asyncio.sleep(1.1)
    assert rig.rt.leases is not None
    await rig.rt.leases.acquire(tid, "run_reviewer")
    assert await rig.poller().poll_once() == []
    assert "open" in (await rig.timers(tid)).values()
    await rig.rt.leases.release(tid, "run_reviewer")
    assert len(await rig.poller().poll_once()) == 1


async def test_poller_killed_after_accepting_leaves_the_timer_due(rig: Rig) -> None:
    tid = await rig.start("sla_killed", sla="1s", onTimeout="escalate", escalateTo="supervisors")
    await asyncio.sleep(1.1)

    async def die() -> None:
        raise SystemExit("poller killed between taking the timer and resuming the thread")

    with pytest.raises(SystemExit):
        await rig.poller(after_accept=die).poll_once()
    assert "open" in (await rig.timers(tid)).values()
    # The dead poller still holds the thread's lease; once it expires, E2's sweeper puts the thread back to waiting.
    await asyncio.sleep(LEASE_TTL + 0.2)
    await sweep_once(rig.rt)
    kinds = [r["kind"] for r in (await rig.client.get(f"/v1/threads/{tid}/runs")).json()["data"]]
    assert kinds.count("recovery") == 1, kinds
    assert len(await rig.poller().poll_once()) == 1
    assert sla(await rig.state(tid))["round"] == 1
    assert list((await rig.timers(tid)).values()).count("fired") == 1


async def test_customer_reply_restarts_the_clock(rig: Rig) -> None:
    tid = await rig.start("sla_reply", sla="2s", onTimeout="escalate", escalateTo="supervisors")
    await asyncio.sleep(1.5)
    r = await rig.client.post(f"/v1/threads/{tid}/events", json={"type": "customer_reply"})
    assert r.status_code == 200, r.text
    await asyncio.sleep(0.7)  # past the original due time, before the restarted one
    assert await rig.poller().poll_once() == []
    await asyncio.sleep(1.5)
    assert len(await rig.poller().poll_once()) == 1
    assert await rig.events(tid) == ["sla.restarted", "sla.breach", "sla.escalated"]


async def breach_id(rig: Rig, tid: str) -> str:
    return next(t for t in await rig.timers(tid) if ":breach:" in t)


@dataclass(frozen=True)
class Fired:
    """A scheduler's call to `fire`, read as the removed fire route answered: 409 for a timer that will never fire."""

    status_code: int
    body: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self.body


async def fire(rig: Rig, tid: str, timer_id: str) -> Fired:
    """What every scheduler does (c-168: no HTTP route fires a timer; the poller calls `fire` in-process)."""
    r = await timers_module.fire(rig.rt, tid, timer_id)  # type: ignore[arg-type]
    data = {"timerId": r.timer_id, "status": r.status, "runId": r.run_id, "attempts": r.attempts}
    if r.status in timers_module.REFUSED:
        return Fired(409, {"success": False, "error": {"code": f"timer_{r.status}", "details": data}})
    return Fired(200, {"success": True, "data": data})


async def timer_runs(rig: Rig, tid: str) -> int:
    runs = (await rig.client.get(f"/v1/threads/{tid}/runs")).json()["data"]
    return sum(1 for r in runs if r["kind"] == "timer")


async def test_same_timer_fired_twice_resumes_once(rig: Rig) -> None:
    tid = await rig.start("sla_fire_twice", sla="1s", onTimeout="escalate", escalateTo="supervisors")
    timer_id = await breach_id(rig, tid)
    await asyncio.sleep(1.1)
    first, second = await fire(rig, tid, timer_id), await fire(rig, tid, timer_id)
    assert first.json()["data"]["status"] == "fired"
    assert second.json()["data"]["status"] == "duplicate"
    assert await timer_runs(rig, tid) == 1
    assert sla(await rig.state(tid))["round"] == 1


async def test_concurrent_fires_resume_once(rig: Rig) -> None:
    tid = await rig.start("sla_fire_race", sla="1s", onTimeout="escalate", escalateTo="supervisors")
    timer_id = await breach_id(rig, tid)
    await asyncio.sleep(1.1)
    results = await asyncio.gather(*(fire(rig, tid, timer_id) for _ in range(3)))
    statuses = sorted(r.json()["data"]["status"] for r in results)
    assert statuses.count("fired") == 1, statuses
    assert await timer_runs(rig, tid) == 1


async def test_fire_on_a_cancelled_timer_is_refused(rig: Rig) -> None:
    tid = await rig.start("sla_fire_cancelled", sla="1s", onTimeout="escalate", escalateTo="supervisors")
    timer_id = await breach_id(rig, tid)
    await decide(rig.client, tid)
    await asyncio.sleep(1.1)
    r = await fire(rig, tid, timer_id)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "timer_cancelled"
    assert (await rig.state(tid))["values"]["status"] == "replied"


async def test_early_fire_does_nothing(rig: Rig) -> None:
    tid = await rig.start("sla_fire_early", sla="5s", onTimeout="escalate", escalateTo="supervisors")
    timer_id = await breach_id(rig, tid)
    r = await fire(rig, tid, timer_id)
    assert r.json()["data"]["status"] == "not_due"
    assert (await rig.timers(tid))[timer_id] == "open"
    assert sla(await rig.state(tid))["round"] == 0
    assert await timer_runs(rig, tid) == 0


async def test_timer_due_during_a_run_is_cancelled_when_the_run_decides(rig: Rig) -> None:
    tid = await rig.start("sla_due_in_run", sla="1s", onTimeout="escalate", escalateTo="supervisors")
    timer_id = await breach_id(rig, tid)
    await asyncio.sleep(1.1)
    assert rig.rt.leases is not None
    await rig.rt.leases.acquire(tid, "run_reviewer")
    assert (await fire(rig, tid, timer_id)).json()["data"]["status"] == "busy"
    await rig.rt.leases.release(tid, "run_reviewer")
    await decide(rig.client, tid)
    r = await fire(rig, tid, timer_id)
    assert r.status_code == 409 and r.json()["error"]["code"] == "timer_cancelled"
    assert await timer_runs(rig, tid) == 0


async def test_a_resume_that_keeps_failing_is_set_aside(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:

    tid = await rig.start("sla_fire_fails", sla="1s", onTimeout="escalate", escalateTo="supervisors")
    timer_id = await breach_id(rig, tid)
    await asyncio.sleep(1.1)

    async def failing(rt: Runtime, row: dict[str, Any], graph: Any, **kw: Any) -> AsyncIterator[dict[str, Any]]:
        assert rt.leases is not None
        await rt.leases.release(row["id"], kw["run_id"])
        yield {"event": "error", "data": {"message": "model provider down"}}

    monkeypatch.setattr(timers_module, "execute", failing)
    statuses = [(await fire(rig, tid, timer_id)).json()["data"]["status"] for _ in range(timers_module.MAX_ATTEMPTS)]
    assert statuses == ["retry"] * timers_module.MAX_ATTEMPTS
    last = await fire(rig, tid, timer_id)
    assert last.status_code == 409 and last.json()["error"]["code"] == "timer_failed"
    assert (await rig.timers(tid))[timer_id] == "failed"
    assert "sla.fire_failed" in await rig.events(tid)
    assert await rig.poller().poll_once() == []
