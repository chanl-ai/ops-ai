"""Background loops, by failure mode: a database error ends a loop for good, so its work stops unseen; a stopped
process still looks alive; heartbeat writes slow the loop they report on; a process not on the list starts anyway."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from ops_store import background
from ops_store.background import BY_KEY, Beat, Heartbeat, MemoryHeartbeats, state
from ops_store.outbox import Relay
from ops_store.testing import loop_reports_failure


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

    async def fake_wait_for(aw: Any, timeout: float) -> Any:  # noqa: ASYNC109
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


def test_the_knowledge_schedule_is_listed_only_when_the_install_has_plugins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # With no plugin installed kb-service never starts the schedule; listing it anyway would show it late on Background.
    def keys() -> set[str]:
        background.plugins_on.cache_clear()
        return {str(p["key"]) for p in background.report([], "kb", 0.0)}

    dropped, builtin = tmp_path / "plugins", tmp_path / "builtin"
    dropped.mkdir()
    builtin.mkdir()
    monkeypatch.delenv("OPS_PLUGIN_PATHS", raising=False)
    monkeypatch.setenv("OPS_PLUGINS_DIR", str(dropped))
    monkeypatch.setenv("OPS_BUILTIN_PLUGINS_DIR", str(builtin))
    assert "knowledge_schedule" not in keys()
    (dropped / "ops_plugin_desk").mkdir()
    assert "knowledge_schedule" in keys()
    background.plugins_on.cache_clear()


class Health:
    """A service's GET /health/background as a test client reaches it, answered from the loops' heartbeats."""

    def __init__(self, beats: MemoryHeartbeats, service: str) -> None:
        self.beats, self.service = beats, service

    async def get(self, url: str, /) -> Health:
        assert url == "/health/background"
        self.body = {"processes": background.report(await self.beats.read(), self.service, time.time())}
        return self

    def json(self) -> Any:
        return self.body


async def test_the_loop_check_passes_on_a_tripped_loop_and_fails_on_one_whose_error_is_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A process that failed once and recovered still carries that error on its row; a trip that breaks nothing
    must not pass on it."""
    monkeypatch.setattr(background, "BACKOFF_START_S", 0.01)
    beats, stop, fail = MemoryHeartbeats(), asyncio.Event(), [True]

    async def once() -> int:
        if fail[0]:
            fail[0] = False
            raise ConnectionError("database connection refused")
        return 0

    task = asyncio.create_task(background.run("files_retention", once, stop=stop, store=beats, every_s=0.01))
    try:
        client = Health(beats, "files")
        await _until(lambda: any((b.last_ok_at or 0) > (b.last_error_at or float("inf")) for b in beats.beats.values()))
        with pytest.raises(AssertionError, match="did not report a failed pass"):
            await loop_reports_failure(client, "files_retention", lambda: None, within_s=0.2)
        await loop_reports_failure(client, "files_retention", lambda: fail.__setitem__(0, True), within_s=2.0)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5)


async def test_a_retention_sweep_deletes_only_rows_past_their_date_and_reports_as_a_listed_process(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}")
    table = sa.Table(
        "call_audit",
        sa.MetaData(),
        sa.Column[int]("id", sa.Integer, primary_key=True),
        sa.Column[float]("at", sa.Float),
    )
    async with engine.begin() as c:
        await c.run_sync(table.create)
        await c.execute(table.insert(), [{"id": 1, "at": 100.0}, {"id": 2, "at": 900.0}])
    sweep = background.retention(table, table.c.at, 500.0, key="call_audit_retention", service="tools")
    with pytest.raises(ValueError, match="not a registered retention process"):
        await background.run_sweep(sweep.key, engine.begin, stop=asyncio.Event())
    background.register(sweep)
    beats, stop = MemoryHeartbeats(), asyncio.Event()
    try:
        task = asyncio.create_task(
            background.run_sweep(sweep.key, engine.begin, stop=stop, store=beats, clock=lambda: 1000.0)
        )
        await _until(lambda: any(b.last_ok_at for b in beats.beats.values()))
        stop.set()
        await asyncio.wait_for(task, timeout=5)
        async with engine.connect() as c:
            assert list((await c.execute(sa.select(table.c.id))).scalars()) == [2]
        (row,) = [p for p in background.report(await beats.read(), "tools", 1000.0) if p["key"] == sweep.key]
        assert row["state"] == "running" and row["doneHour"] == 1 and row["everySeconds"] == 3600.0
    finally:
        background.PROCESSES.remove(sweep)
        del background.BY_KEY[sweep.key]
        await engine.dispose()
