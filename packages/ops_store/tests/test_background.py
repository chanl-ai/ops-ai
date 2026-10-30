"""Background loops (c-516), by failure mode: a database error ends a loop for good, so its work stops unseen; a stopped
process still looks alive; heartbeat writes slow the loop they report on; a process not on the list starts anyway."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ops_store import background
from ops_store.background import BY_KEY, Beat, Heartbeat, MemoryHeartbeats, state
from ops_store.outbox import Relay


async def _until(cond: Any, *, tries: int = 300) -> None:
    for _ in range(tries):
        if cond():
            return
        await asyncio.sleep(0.01)


async def test_a_relay_keeps_running_after_a_database_error_and_its_heartbeat_shows_it() -> None:
    relay = Relay(engine=None, table=None, send=None)  # type: ignore[arg-type]
    calls = {"once": 0}

    async def once() -> int:
        calls["once"] += 1
        if calls["once"] == 1:
            raise ConnectionError("database connection refused")
        return 3

    async def nothing(**_: Any) -> int:
        return 0

    relay.once = once  # type: ignore[method-assign]
    relay.prune = nothing  # type: ignore[method-assign]
    relay.waiting = nothing  # type: ignore[method-assign]
    beats = MemoryHeartbeats()
    stop = asyncio.Event()
    background.BACKOFF_START_S = 0.01  # the first retry comes at once in the test
    try:
        task = asyncio.create_task(relay.run(stop, key="files_relay", store=beats, every_s=0.01))
        await _until(lambda: calls["once"] >= 2)
        stop.set()
        await asyncio.wait_for(task, timeout=5)
    finally:
        background.BACKOFF_START_S = 1.0
    assert calls["once"] >= 2, "the relay stopped after its first database error"
    (beat,) = await beats.read()
    assert beat.last_error == "ConnectionError: database connection refused"
    assert beat.last_ok_at and beat.last_error_at and beat.last_ok_at > beat.last_error_at, (
        "the recovery was not written"
    )
    assert state(beat, BY_KEY["files_relay"], beat.last_ok_at) == "running"


async def test_a_failing_pass_waits_longer_each_time_up_to_a_minute() -> None:
    waits: list[float] = []
    beat_store = MemoryHeartbeats()
    stop = asyncio.Event()

    async def once() -> int:
        raise ConnectionError("down")

    real = asyncio.wait_for

    async def fake_wait_for(aw: Any, timeout: float) -> Any:
        waits.append(timeout)
        if len(waits) >= 8:
            stop.set()
        aw.close()
        raise TimeoutError

    asyncio.wait_for = fake_wait_for  # type: ignore[assignment]
    try:
        await real(background.run("sweeper", once, stop=stop, store=beat_store), timeout=5)
    finally:
        asyncio.wait_for = real
    assert waits == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]


async def test_many_quick_passes_write_one_heartbeat() -> None:
    writes: list[Heartbeat] = []

    class Counting(MemoryHeartbeats):
        async def write(self, beat: Heartbeat) -> None:
            writes.append(beat)

    now = [1000.0]
    beat = Beat("workflow_worker", Counting(), clock=lambda: now[0])
    for _ in range(100):
        now[0] += 0.01
        await beat.ok(1)
    assert len(writes) == 1
    now[0] += background.WRITE_EVERY_S
    await beat.ok(1)
    assert len(writes) == 2 and writes[-1].done_hour == 101


def test_state_is_late_after_two_gaps_and_stopped_after_five() -> None:
    """A gap is the interval or the heartbeat's write gap, whichever is longer: the worker polls every 0.5 s and its
    heartbeat is written every 10 s, so it is late after 20 s, not after the second it never wrote."""
    worker = BY_KEY["workflow_worker"]
    beat = Heartbeat(process="workflow_worker", instance="h:1", started_at=0.0, last_run_at=100.0, last_ok_at=100.0)
    assert state(beat, worker, 115.0) == "running"
    assert state(beat, worker, 121.0) == "late"
    assert state(beat, worker, 151.0) == "stopped"
    cleanup = BY_KEY["memory_cleanup"]  # hourly, its first pass an hour after start
    waiting = Heartbeat(process="memory_cleanup", instance="h:1", started_at=0.0, next_run_at=3600.0)
    assert state(waiting, cleanup, 1800.0) == "running"
    assert state(None, worker, 0) == "not_reported"
    failed = Heartbeat(process="event_workflows", instance="h:1", started_at=0.0, last_ok_at=5.0, last_error_at=6.0)
    assert state(failed, BY_KEY["event_workflows"], 7.0) == "stopped"


def test_a_process_not_on_the_list_does_not_start() -> None:
    with pytest.raises(ValueError, match=r"not on ops_store\.background\.PROCESSES"):
        Beat("nightly_export", MemoryHeartbeats())


def test_the_knowledge_schedule_is_listed_only_with_plugins_on(monkeypatch: pytest.MonkeyPatch) -> None:
    # With OPS_PLUGINS off kb-service never starts the schedule; listing it anyway would show it late on Background.
    def keys() -> set[str]:
        background.plugins_on.cache_clear()
        return {str(p["key"]) for p in background.report([], "kb", 0.0)}

    monkeypatch.delenv("OPS_PLUGINS", raising=False)
    assert "knowledge_schedule" not in keys()
    monkeypatch.setenv("OPS_PLUGINS", "true")
    assert "knowledge_schedule" in keys()
    background.plugins_on.cache_clear()
