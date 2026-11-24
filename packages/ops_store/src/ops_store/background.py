"""Background processes: work that runs without a person asking, one list of it, and a heartbeat per process.

A background process is central and the work it does is in a team: one copy runs for the account, finds its next job
across teams, and does that job inside the job's own team. Every process is on `PROCESSES`; a loop starts only through
`run`, which refuses a key not on the list, keeps going after an error with a growing wait, and writes a heartbeat. A
process that runs on events instead of a timer reports through `Beat` directly.

  beats = MemoryHeartbeats()                     # or DbHeartbeats(engine, heartbeats_table(metadata))
  await run("files_relay", relay.once, stop=stop, store=beats, every_s=2.0, waiting=relay.waiting)
  beats.read()  -> the rows `/health/background` answers from

A task that outlives the request that starts it goes on the lifespan's TaskGroup, never a bare `create_task`:

  async with background.supervisor():           # in the lifespan, around `yield`
      ...
  await background.start(retry_hand_off(item), key="tools_review_handoff")

A table that only grows gets a sweep the same way: `register(retention(table, table.c.at, keep_s, key=...,
service=...))` lists it, and `run_sweep(key, tx, stop=stop)` runs it. A listed process whose pass is the service's
own (a purge that deletes bytes and writes events) is given it, and run the same way:

  give_pass("files_retention", lambda _tx, _now: files.purge_released(), service="files")
  await run_sweep("files_retention", stop=stop)   # no tx: the pass opens its own transactions
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from dataclasses import asdict, dataclass, field, replace
from functools import cache
from typing import Any, Literal, Protocol, TypedDict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.logging import get_logger
from ops_service_kit.settings import Settings

from . import isolation
from .schema import system

log = get_logger(__name__)

# One pass of a retention sweep: deletes what is past its date as of `now` on the caller's connection and returns
# how many rows went.
Sweep = Callable[[AsyncConnection, float], Awaitable[int]]
# Opens one transaction of a pass: the service's `system_tx` with its reason and role.
Tx = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
# A pass that opens its own transactions with `tx`, for one that calls another service between them and so must hold
# no transaction across that call (a copy's resync), at `now`; returns how many rows changed.
Cycle = Callable[[Tx, float], Awaitable[int]]


@dataclass(frozen=True)
class Process:
    """One background process: `every_s` is its interval, None for one that runs on events; `across_teams` says why it
    looks across teams to find its work."""

    key: str
    service: str
    title: str
    does: str
    every_s: float | None
    across_teams: str
    # Listed only while this answers true: a process behind a switch is neither started nor reported late while off.
    only_if: Callable[[], bool] | None = None
    # A retention process's one pass (`retention`); None for a process whose service supplies its own.
    sweep: Sweep | None = None
    # A pass that opens its own transactions; `run_sweep` runs it instead of `sweep` when set.
    cycle: Cycle | None = None


@cache
def plugins_on() -> bool:
    """Whether the install has any plugin (Settings.plugins), read once per process."""
    return Settings().plugins


PROCESSES: list[Process] = [
    Process(
        "workflow_worker",
        "agents",
        "Workflow worker",
        "Runs workflow steps and agent turns that are waiting.",
        0.5,
        "It claims the next waiting step of any team's run, then runs it in that run's team.",
    ),
    Process(
        "sweeper",
        "agents",
        "Sweeper",
        "Picks up runs whose worker stopped, and finishes or retries them.",
        3.0,
        "A stopped worker's runs can belong to any team; each is recovered in its own team.",
    ),
    Process(
        "run_reconciler",
        "agents",
        "Run reconciler",
        "Marks workflow runs that nothing is working on as Stuck, so a person can retry or cancel them.",
        60.0,
        "A run with nothing behind it can belong to any team; each is marked in its own team.",
    ),
    Process(
        "batch_starter",
        "agents",
        "Batch starter",
        "Starts the runs of each batch's rows, up to 50 a pass, and stops a batch whose rows met the model budget.",
        2.0,
        "Pending rows can belong to any team; each row's run starts in its own team.",
    ),
    Process(
        "timer_poller",
        "agents",
        "Timer poller",
        "Wakes runs waiting for a time, a date or a reminder.",
        1.0,
        "Timers of every team fall due on one clock; each run wakes in its own team.",
    ),
    Process(
        "memory_cleanup",
        "agents",
        "Memory clean-up",
        "Deletes agent memories past their retention.",
        3600.0,
        "Retention is set per workspace; each team's memories are deleted in that team.",
    ),
    Process(
        "mail_listener",
        "agents",
        "Mail listener",
        "Reads each connected mailbox and starts the workflow bound to it.",
        30.0,
        "Every team's live mailbox workflows are read; each run starts in its workflow's team.",
    ),
    Process(
        "schedule_clock",
        "agents",
        "Schedule clock",
        "Starts each live workflow's scheduled runs at their times, and records a tick it skipped or could not start.",
        60.0,
        "Every team's saved schedules are read beside their live workflows; each run starts in its workflow's team.",
    ),
    Process(
        "event_workflows",
        "agents",
        "Event workflows",
        "Runs the five built-in event workflows: tool access requests, reading a file for the system, purging a "
        "deleted file, saving a checker's corrections and tasks opened through the API.",
        None,
        "One copy serves the account; each run acts in the team of the event that started it.",
    ),
    Process(
        "files_relay",
        "files",
        "File hand-off",
        "Tells other services a file arrived, changed or was deleted.",
        2.0,
        "It delivers every team's file events, each as its own team.",
    ),
    Process(
        "files_retention",
        "files",
        "File retention",
        "Deletes knowledge snapshots their sources let go once their days have passed, and watched-folder events "
        "older than 90 days.",
        3600.0,
        "It lists every team's released snapshots past their date, then deletes each as its own team; it deletes "
        "every team's old watch events in one statement.",
    ),
    Process(
        "files_watch_checks",
        "files",
        "Watched folder checks",
        "Checks each watched folder someone asked to check, bringing its new and changed files into Files.",
        5.0,
        "It lists every team's asked-for checks, then checks each folder as its own team under the folder's lease.",
    ),
    Process(
        "documents_relay",
        "documents",
        "Document hand-off",
        "Tells other services what a document read found.",
        2.0,
        "It delivers every team's document events, each as its own team.",
    ),
    Process(
        "tools_relay",
        "tools",
        "Tool events",
        "Sends tool-call and access events on.",
        2.0,
        "It delivers every team's tool events, each as its own team.",
    ),
    Process(
        "sign_in_keepalive",
        "tools",
        "Sign-in keep-alive",
        "Refreshes every account sign-in unused for 20 days, so a system that ends idle sign-ins keeps them.",
        86400.0,
        "Any team's sign-ins can go unused; each team's are refreshed in that team.",
    ),
    Process(
        "sign_in_test",
        "tools",
        "Test after sign-in",
        "Tests an account right after it signs in, when its app names a test, without holding the sign-in's answer.",
        None,
        "It tests one account, in the team that signed in.",
    ),
    Process(
        "document_reading",
        "documents",
        "Document reading",
        "Reads queued files and runs document type tests.",
        None,
        "Reads queued before a restart are resumed for every team, each in its own team.",
    ),
    Process(
        "agents_relay",
        "agents",
        "Agents hand-off",
        "Sends schedule saves and clears to the account's audit log.",
        2.0,
        "It delivers every team's entries, each as its own team.",
    ),
    Process(
        "kb_relay",
        "kb",
        "Knowledge hand-off",
        "Sends knowledge settings changes to the account's audit log and failing-source alerts to the agents service.",
        2.0,
        "It delivers every team's entries and alerts, each as its own team.",
    ),
    Process(
        "kb_embed",
        "kb",
        "Knowledge embedding",
        "Embeds knowledge pieces that have no vector of the environment's embedding model yet.",
        30.0,
        "Every team's pieces are embedded, each in its own team; a model that is down is tried again next pass.",
    ),
    Process(
        "knowledge_schedule",
        "kb",
        "Knowledge schedule",
        "Syncs each knowledge source read through a plugin's tools when its schedule is due.",
        60.0,
        "Every team's tool sources are checked for being due; each syncs in its own team.",
        only_if=plugins_on,
    ),
    Process(
        "workspace_lifecycle",
        "platform",
        "Workspace purge",
        "Removes the records of workspaces closed longer than the restore window.",
        900.0,
        "Any workspace's restore window can end; each is purged in its own tenant.",
    ),
    Process(
        "signin_watch",
        "platform",
        "Sign-in certificates",
        "Re-reads SAML providers' metadata for new certificates and tells Security admins before one ends.",
        86400.0,
        "Every workspace's SAML providers are checked once a day; each is read and changed in its own tenant.",
    ),
    Process(
        "platform_relay",
        "platform",
        "Platform events",
        "Tells other services about people and teams, such as a member removed from a team.",
        2.0,
        "It delivers every team's people and team events, each as its own team.",
    ),
]
BY_KEY: dict[str, Process] = {p.key: p for p in PROCESSES}

# How often a retention sweep runs: what it deletes is days old, so an hour's delay is not seen.
RETENTION_EVERY_S = 3600.0


def register(process: Process) -> Process:
    """Lists a process a service defines beside its own tables (a retention sweep), so it may start and shows on
    that service's /health/background. Listing the same process again changes nothing; a key already taken by a
    different one is refused."""
    listed = BY_KEY.get(process.key)
    if listed is not None:
        if (listed.service, listed.title) != (process.service, process.title):
            raise ValueError(f"{process.key!r} is already on ops_store.background.PROCESSES for {listed.service}")
        return listed
    PROCESSES.append(process)
    BY_KEY[process.key] = process
    return process


def give_pass(key: str, cycle: Cycle, *, service: str, every_s: float | None = None) -> Process:
    """Gives the listed process `key` the pass `run_sweep` runs, for one whose work is not a row delete. Its row keeps
    its title and description, and its interval unless `every_s` is given. Giving one again replaces it: each app a
    process builds (a test's, a restart's) brings its own store. A key not listed, listed for another service, or
    a retention process with its own sweep is refused."""
    listed = BY_KEY.get(key)
    if listed is None:
        raise ValueError(f"{key!r} is not on ops_store.background.PROCESSES; list it before giving it a pass")
    if listed.service != service:
        raise ValueError(f"{key} belongs to {listed.service}, not {service}")
    if listed.sweep is not None:
        raise ValueError(f"{key} has its own sweep")
    given = replace(listed, cycle=cycle, every_s=every_s if every_s is not None else listed.every_s)
    PROCESSES[PROCESSES.index(listed)] = given
    BY_KEY[key] = given
    return given


def retention(table: sa.Table, at: sa.Column[float], keep_s: float, *, key: str, service: str) -> Process:
    """The process that keeps an append-only table from growing without end: each pass deletes the rows whose `at`
    (Unix seconds) is more than `keep_s` old. A pass that finds nothing writes nothing. Not listed until
    `register`ed; `run_sweep` runs it."""

    async def sweep(conn: AsyncConnection, now: float) -> int:
        gone = await conn.execute(table.delete().where(at < now - keep_s))
        return int(gone.rowcount or 0)

    days = keep_s / 86400.0
    return Process(
        key,
        service,
        f"Retention of {table.name}",
        f"Deletes rows of {table.name} older than {days:g} days.",
        RETENTION_EVERY_S,
        "Rows of every team pass their date on one clock; the sweep deletes them as the service's system role.",
        sweep=sweep,
    )


# A listed process whose loop cannot go through `run` (it runs passes concurrently, or holds IDLE connections beside
# its poll) and reports through a `Beat` instead: its function, by dotted name, and its process key.
LOOPS: dict[str, str] = {
    "ops_engine.worker.Worker.run_forever": "workflow_worker",
    "ops_agents.api.email_trigger.EmailTriggers.run_forever": "mail_listener",
}

# Functions that wait in a loop but are not background processes: `test_background_registry.py` lets these through.
EXEMPT: dict[str, str] = {
    "ops_store.background.run": "the one runner every listed process loops through",
    "ops_agents.api.routers.events.*": "a request's event stream, polled while the caller listens",
    "ops_agents.api.routers.tasks.*": "a request waiting up to OPEN_WAIT for its task to open",
    "ops_agents.api.routers.engine.*": "a request's run stream, polled while the caller listens",
    "ops_agents.graphs.sla.*": "a review's interrupt loop inside one graph run",
    "ops_agents.store.leases.Heartbeat._loop": "renews one run's lease while the run goes; part of the workflow worker",
    "ops_engine.worker.Worker._renew": "renews one turn's claim while the turn runs; part of the workflow worker",
    "ops_agents.api.routers.chat._renew": "renews one chat turn's claim while the reply streams; part of the workflow "
    "worker's queue",
    "ops_engine.worker.Worker._heartbeat": "renews one run's claim while a pass runs; part of the workflow worker",
    "ops_kb.service.Lease._keep": "renews one sync's source lease while the sync or rebuild runs",
    "ops_engine.compiler.*": "waits inside one compiled step",
    "ops_tools.transform.*": "waits on one call's child process",
    "ops_runner.wasm.*": "waits inside one code run, for its guest's pipes and lines, bounded by the run's time limit",
    "ops_tools.opa.*": "retries loading the policy at start-up",
    "ops_kb.__main__.wait_for_files": "start-up probe of files-service, bounded by ready_wait_s, then ends",
    "ops_identity.client.*": "pages through one list call",
    "ops_email.inbound.*": "reads one mailbox for the mail listener",
    "ops_agents.api.email_trigger.EmailTriggers.idle_forever": "holds one mailbox's IDLE connection; mail listener",
    "ops_tools.modules.review_handoff.keep_handing_over": "retries one hand-off at start-up, then ends",
    "ops_documents_client.DocumentsClient.extract": "a caller polling its own extraction until it finishes",
    "ops_store.conformance._until": "the conformance suite waiting for a condition",
    "ops_agents.api.child_runs.ChildRuns._run_engine": "a chat turn waiting for the workflow run it started",
    "ops_tools.file_tools.FileTools._finished": "one file-tool call waiting, within its deadline, for its extraction",
}

State = Literal["running", "late", "stopped", "not_reported"]

# A heartbeat is written at most this often while passes succeed; an error is written at once.
WRITE_EVERY_S = 10.0
# After an error the loop waits 1 s, doubling each failure, up to a minute.
BACKOFF_START_S, BACKOFF_MAX_S = 1.0, 60.0
# Late after this many intervals without a pass, stopped after STOPPED_AFTER. A heartbeat is written at most every
# WRITE_EVERY_S, so the count is of whichever is longer, the interval or the write gap: a worker polling every half
# second is late after 20 s, not after one second it never wrote.
LATE_AFTER, STOPPED_AFTER = 2, 5
# An event-run process's passes are separate pieces of work (one file read, one event), so a later success does not
# mean an earlier failure recovered: its row keeps the failure (lastError, lastErrorAt) for this long, the hour
# doneHour counts, then drops it. Its state still follows the last pass, since `make health` counts stopped as down.
FAILURE_SHOWN_S = 3600.0


def instance_name() -> str:
    """This process's name among several of one kind: host and pid."""
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass
class Heartbeat:
    process: str
    instance: str
    started_at: float
    last_run_at: float | None = None
    last_ok_at: float | None = None
    next_run_at: float | None = None
    done_hour: int = 0
    waiting: int | None = None
    last_error: str | None = None
    last_error_at: float | None = None

    def as_row(self) -> dict[str, str | float | int | None]:
        return asdict(self)


def state(beat: Heartbeat | None, process: Process, now: float) -> State:
    """Running while the last pass is within LATE_AFTER intervals, late after that, stopped after STOPPED_AFTER or
    while the last pass failed. An event-run process is running unless its last pass failed or work waits unclaimed."""
    if beat is None:
        return "not_reported"
    failed = beat.last_error_at is not None and (beat.last_ok_at is None or beat.last_error_at > beat.last_ok_at)
    if failed:
        return "stopped"
    if process.every_s is None:
        return "running"
    since = now - (beat.last_run_at or beat.started_at)
    gap = max(process.every_s, WRITE_EVERY_S)
    if beat.last_run_at is None and beat.next_run_at is not None:
        # Started, and its first pass is not due yet (memory clean-up waits an hour).
        since = now - beat.next_run_at
    if since > STOPPED_AFTER * gap:
        return "stopped"
    if since > LATE_AFTER * gap:
        return "late"
    return "running"


class HeartbeatStore(Protocol):
    async def write(self, beat: Heartbeat) -> None: ...
    async def read(self) -> list[Heartbeat]: ...


@dataclass
class MemoryHeartbeats:
    """Heartbeats of the loops in this one process, for a service whose loops run beside its web server."""

    beats: dict[tuple[str, str], Heartbeat] = field(default_factory=dict[tuple[str, str], Heartbeat])

    async def write(self, beat: Heartbeat) -> None:
        self.beats[(beat.process, beat.instance)] = replace(beat)

    async def read(self) -> list[Heartbeat]:
        return list(self.beats.values())


HEARTBEATS = system("background process heartbeats, one row per process instance, no tenant data")
# Why heartbeats are read and written past the tenant: they describe a process, which serves every tenant.
HEARTBEAT = "background_heartbeat"


def heartbeats_table(metadata: sa.MetaData, name: str = "background_heartbeats") -> sa.Table:
    """The heartbeat columns, for a service whose processes run apart from its web server (agents-service's worker)."""
    return sa.Table(
        name,
        metadata,
        sa.Column("process", sa.String(64), primary_key=True),
        sa.Column("instance", sa.String(200), primary_key=True),
        sa.Column("started_at", sa.Float(asdecimal=False), nullable=False),
        sa.Column("last_run_at", sa.Float(asdecimal=False)),
        sa.Column("last_ok_at", sa.Float(asdecimal=False)),
        sa.Column("next_run_at", sa.Float(asdecimal=False)),
        sa.Column("done_hour", sa.Integer, nullable=False, server_default="0"),
        sa.Column("waiting", sa.Integer),
        sa.Column("last_error", sa.String(2000)),
        sa.Column("last_error_at", sa.Float(asdecimal=False)),
        info=HEARTBEATS,
    )


class DbHeartbeats:
    """Heartbeats in the service's own database: one row per process instance, replaced on each write. The table holds
    no tenant data and is reached through `isolation.system_tx`, as `role` (the service's system role)."""

    def __init__(self, engine: AsyncEngine, table: sa.Table, *, role: str | None = None) -> None:
        self.engine, self.table, self.role = engine, table, role

    async def write(self, beat: Heartbeat) -> None:
        t, row = self.table, beat.as_row()
        async with isolation.system_tx(self.engine, HEARTBEAT, role=self.role) as conn:
            changed = await conn.execute(
                t.update().where(t.c.process == beat.process, t.c.instance == beat.instance).values(**row)
            )
            if not changed.rowcount:
                await conn.execute(t.insert().values(**row))

    async def read(self) -> list[Heartbeat]:
        async with isolation.system_tx(self.engine, HEARTBEAT, role=self.role) as conn:
            rows = (await conn.execute(sa.select(self.table))).mappings()
            return [Heartbeat(**dict(r)) for r in rows]

    async def forget_older_than(self, cutoff: float) -> None:
        """Drops rows of instances that have not run since `cutoff` (a process restarted under a new pid)."""
        t = self.table
        async with isolation.system_tx(self.engine, HEARTBEAT, role=self.role) as conn:
            await conn.execute(t.delete().where(sa.func.coalesce(t.c.last_run_at, t.c.started_at) < cutoff))


class Beat:
    """One process's heartbeat while it runs: count what each pass did, record failures, and write at most every
    WRITE_EVERY_S, at once on an error and on the first pass after one."""

    def __init__(
        self, key: str, store: HeartbeatStore, *, clock: Callable[[], float] = time.time, instance: str | None = None
    ) -> None:
        if key not in BY_KEY:
            raise ValueError(f"{key!r} is not on ops_store.background.PROCESSES; list it before starting it")
        self.process, self.store, self.clock = BY_KEY[key], store, clock
        self.beat = Heartbeat(process=key, instance=instance or instance_name(), started_at=clock())
        self._minutes: deque[tuple[int, int]] = deque()
        self._written = float("-inf")

    def write_due(self) -> bool:
        """Whether the next successful pass will write, so a caller asks for the waiting count only then."""
        return self.clock() - self._written >= WRITE_EVERY_S

    def _count(self, n: int, now: float) -> int:
        minute = int(now // 60)
        if self._minutes and self._minutes[-1][0] == minute:
            self._minutes[-1] = (minute, self._minutes[-1][1] + n)
        else:
            self._minutes.append((minute, n))
        while self._minutes and self._minutes[0][0] <= minute - 60:
            self._minutes.popleft()
        return sum(c for _, c in self._minutes)

    async def started(self, *, next_in: float) -> None:
        """Written once at start, so a process whose first pass is a while off shows as running until then."""
        self.beat.next_run_at = self.clock() + next_in
        await self._write(self.clock(), force=True)

    async def ok(
        self, done: int = 0, *, waiting: int | None = None, next_in: float | None = None, force: bool = False
    ) -> None:
        """`force` writes now: a started task's pass is rare and its count would otherwise wait for the next write."""
        now = self.clock()
        recovering = force or (
            self.beat.last_error_at is not None and (self.beat.last_ok_at or 0) < self.beat.last_error_at
        )
        self.beat.last_run_at = self.beat.last_ok_at = now
        self.beat.done_hour = self._count(done, now)
        self.beat.next_run_at = now + next_in if next_in is not None else None
        if waiting is not None:
            self.beat.waiting = waiting
        await self._write(now, force=recovering)

    async def failed(self, error: BaseException, *, next_in: float | None = None) -> None:
        now = self.clock()
        self.beat.last_run_at = self.beat.last_error_at = now
        self.beat.last_error = f"{type(error).__name__}: {error}"[:2000]
        self.beat.next_run_at = now + next_in if next_in is not None else None
        await self._write(now, force=True)

    async def _write(self, now: float, *, force: bool) -> None:
        if not force and now - self._written < WRITE_EVERY_S:
            return
        try:
            await self.store.write(self.beat)
            self._written = now
        except Exception:
            log.warning("background_heartbeat_unwritten", process=self.beat.process, exc_info=True)


async def run(
    key: str,
    once: Callable[[], Awaitable[int | None]],
    *,
    stop: asyncio.Event,
    store: HeartbeatStore,
    every_s: float | None = None,
    waiting: Callable[[], Awaitable[int]] | None = None,
    clock: Callable[[], float] = time.time,
    instance: str | None = None,
    first_in: float = 0.0,
) -> None:
    """Runs `once` every `every_s` (the listed interval by default) until `stop` is set, the first time after
    `first_in` seconds. A pass that raises is logged
    and recorded, and the next one comes after 1 s, doubling to a minute, so a database that comes back is picked up
    without a restart. `waiting` counts the work not yet done, asked once per heartbeat write."""
    beat = Beat(key, store, clock=clock, instance=instance)
    every = every_s if every_s is not None else beat.process.every_s or 1.0
    backoff = BACKOFF_START_S
    if first_in > 0:
        await beat.started(next_in=first_in)
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=first_in)
    while not stop.is_set():
        try:
            done = await once()
            queue = await waiting() if waiting is not None and beat.write_due() else None
            await beat.ok(int(done or 0), waiting=queue, next_in=every)
            pause, backoff = every, BACKOFF_START_S
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(
                "background_pass_failed", process=key, error=f"{type(e).__name__}: {e}"[:500], retry_in_s=backoff
            )
            await beat.failed(e, next_in=backoff)
            pause, backoff = backoff, min(BACKOFF_MAX_S, backoff * 2)
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=pause)


# The heartbeats of loops running inside this one process (files, documents and tools run theirs beside their web
# server); `/health/background` answers from it.
LOCAL = MemoryHeartbeats()


class NoSupervisor(RuntimeError):
    """`start` was called outside a lifespan that holds `supervisor()`."""


@dataclass
class _Group:
    """One lifespan's TaskGroup, its tasks still running, and the one heartbeat per key (and store) its tasks share."""

    group: asyncio.TaskGroup
    tasks: set[asyncio.Task[None]] = field(default_factory=set[asyncio.Task[None]])
    beats: dict[tuple[str, int], Beat] = field(default_factory=dict[tuple[str, int], Beat])


# The TaskGroups of the lifespans running in this process, innermost last; `start` puts a task on the last.
_GROUPS: list[_Group] = []


@asynccontextmanager
async def supervisor() -> AsyncGenerator[None]:
    """Held by a service's lifespan around its `yield`: the TaskGroup every `start`ed task runs on. Leaving it cancels
    the tasks still running and waits for them, so nothing a request started outlives the process's shutdown."""
    async with asyncio.TaskGroup() as group:
        held = _Group(group)
        _GROUPS.append(held)
        try:
            yield
        finally:
            _GROUPS.remove(held)
            for task in held.tasks:
                task.cancel()


async def start(coro: Coroutine[Any, Any, None], *, key: str, store: HeartbeatStore = LOCAL) -> None:
    """A task that outlives the request: on the lifespan's TaskGroup, cancelled at shutdown, its failure on
    /health/background under key. Its own asyncio task, so its own transaction.

    A failure is caught and recorded rather than raised, so one failed task never cancels the group's others. Every
    task under one key shares the lifespan's one heartbeat for it: a later task's success does not write over an
    earlier one's failure, and doneHour counts them all."""
    if not _GROUPS:
        coro.close()
        raise NoSupervisor("background.start needs the lifespan to hold background.supervisor()")
    held = _GROUPS[-1]
    beat = held.beats.get((key, id(store)))
    if beat is None:
        beat = held.beats[(key, id(store))] = Beat(key, store)

    async def supervised() -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("background_task_failed", process=key, error=f"{type(e).__name__}: {e}"[:500])
            await beat.failed(e)
        else:
            await beat.ok(1, force=True)

    task = held.group.create_task(supervised(), name=key)
    held.tasks.add(task)
    task.add_done_callback(held.tasks.discard)


async def run_sweep(
    key: str,
    tx: Tx | None = None,
    *,
    stop: asyncio.Event,
    store: HeartbeatStore = LOCAL,
    clock: Callable[[], float] = time.time,
    every_s: float | None = None,
) -> None:
    """Runs the registered retention process `key` until `stop` is set, one pass per listed interval. `tx` opens the
    transaction a pass deletes in: the service's own `system_tx` with its reason and role, since the rows are every
    tenant's. A process with a `cycle` is handed `tx` and opens its transactions itself; one given by `give_pass`
    that opens its own needs no `tx`."""
    process = BY_KEY.get(key)
    cycle = None if process is None else process.cycle or (_in_one_tx(process.sweep) if process.sweep else None)
    if cycle is None:
        raise ValueError(f"{key!r} is not a registered retention process; register(retention(...)) it first")
    if tx is None and process is not None and process.sweep is not None:
        raise ValueError(f"{key} deletes in the caller's transaction; pass run_sweep its tx")
    opens = tx or _no_tx(key)

    async def once() -> int:
        return await cycle(opens, clock())

    await run(key, once, stop=stop, store=store, every_s=every_s, clock=clock)


def _no_tx(key: str) -> Tx:
    def refuse() -> AbstractAsyncContextManager[AsyncConnection]:
        raise ValueError(f"{key}'s pass opened run_sweep's transaction, and run_sweep was given none")

    return refuse


def _in_one_tx(sweep: Sweep) -> Cycle:
    async def cycle(tx: Tx, now: float) -> int:
        async with tx() as conn:
            return await sweep(conn, now)

    return cycle


class ProcessReport(TypedDict):
    """One process in a service's background health reply, as `report()` builds it."""

    key: str
    service: str
    title: str
    does: str
    everySeconds: float | None
    state: State
    instances: int
    lastRunAt: float | None
    nextRunAt: float | None
    doneHour: int
    waiting: int | None
    lastError: str | None
    lastErrorAt: float | None


def report(beats: list[Heartbeat], service: str, now: float, *, detail: bool = False) -> list[ProcessReport]:
    """One entry per listed process of `service`, with its instances' heartbeats and a state. Without `detail` an
    error is its type only, so an unauthenticated health check carries no record's data."""
    out: list[ProcessReport] = []
    for p in (p for p in PROCESSES if p.service == service and (p.only_if is None or p.only_if())):
        gap = STOPPED_AFTER * max(p.every_s or 0.0, WRITE_EVERY_S)
        # An instance that stopped beating (a restarted process under a new pid) no longer counts as one running.
        mine = [b for b in beats if b.process == p.key]
        live = [b for b in mine if now - (b.last_run_at or b.started_at) <= gap or p.every_s is None]
        newest = max(mine, key=lambda b: b.last_run_at or b.started_at, default=None)
        error, error_at = (newest.last_error, newest.last_error_at) if newest else (None, None)
        if p.every_s is None and error_at is not None and now - error_at >= FAILURE_SHOWN_S:
            error = error_at = None
        out.append(
            {
                "key": p.key,
                "service": p.service,
                "title": p.title,
                "does": p.does,
                "everySeconds": p.every_s,
                "state": state(newest, p, now),
                "instances": len(live),
                "lastRunAt": newest.last_run_at if newest else None,
                "nextRunAt": newest.next_run_at if newest else None,
                "doneHour": sum(b.done_hour for b in live),
                "waiting": max((b.waiting for b in live if b.waiting is not None), default=None),
                "lastError": (error if detail else error.split(":", 1)[0]) if error else None,
                "lastErrorAt": error_at,
            }
        )
    return out
