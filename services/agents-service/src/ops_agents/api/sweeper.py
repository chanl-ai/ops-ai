"""The sweeper: finds threads whose lease expired (their process died mid-run), records the dead run as crashed,
takes the lease, and continues the thread from its last checkpoint on this process.

LangGraph continues from a checkpoint when invoked with no input: tasks that finished before the crash keep their
saved writes, and the task that was running when the process died runs again from its start. A run that died before
its first checkpoint has nothing to continue, so it is restarted with the input the journal kept.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.types import Command

from ops_engine.store import RUN_PREFIX
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.logging import get_logger

from ..store.leases import LeaseHeldError
from .deps import Runtime
from .email_trigger import POLL_LEASE_PREFIX
from .runs import config, execute, graph_store, require_graphs, resolve
from .tenant_tasks import as_thread_tenant

log = get_logger("ops_agents.api.sweeper")


async def recover(
    rt: Runtime, thread_id: str, dead_run_id: str, *, dead_owner: str | None = None, dead_generation: int | None = None
) -> str | None:
    """Continues one thread whose lease expired. Returns the recovery run id, or None when another sweeper won."""
    store, leases = graph_store(rt), rt.leases
    assert leases is not None
    run_id = new_id("run")
    try:
        generation = await leases.acquire(thread_id, run_id)
    except LeaseHeldError:
        return None  # Another process's sweeper, or a new run, took it first.
    row, graph = await resolve(rt, thread_id)
    snapshot = await graph.aget_state(config(thread_id))
    await store.mark_crashed(
        dead_run_id,
        now_iso(),
        owner=dead_owner,
        running=list(snapshot.next),
        generation=dead_generation,
        by_generation=generation,
    )
    graph_input: Any = None
    if not snapshot.created_at:
        dead = await store.run(dead_run_id) or {}
        journal: dict[str, Any] = dead.get("input") or {}
        graph_input = Command(resume=journal["resume"]) if "resume" in journal else journal.get("input")
    if not await store.start_run(
        run_id, thread_id, "recovery", now_iso(), {"recovers": dead_run_id}, generation=generation
    ):
        await leases.release(thread_id, run_id)
        return None
    log.info("recovery_started", thread=thread_id, crashed_run=dead_run_id, run=run_id, owner=leases.owner)
    async for _ in execute(rt, row, graph, graph_input=graph_input, run_id=run_id, kind="recovery"):
        pass
    log.info("recovery_finished", thread=thread_id, run=run_id)
    return run_id


async def sweep_once(rt: Runtime) -> list[str]:
    require_graphs(rt)
    assert rt.leases is not None
    recovered: list[str] = []
    for lease in await rt.leases.expired():
        if lease.thread_id.startswith(RUN_PREFIX):
            continue  # A workflow runner thread: its worker reclaims it through the lapsed work claim, never this loop.
        if lease.thread_id.startswith(POLL_LEASE_PREFIX):
            continue  # A mailbox poll's lease: the next poll takes it over once it has expired.
        try:
            if run := await as_thread_tenant(
                rt,
                lease.thread_id,
                lambda lease=lease: recover(
                    rt, lease.thread_id, lease.run_id, dead_owner=lease.owner, dead_generation=lease.generation
                ),
            ):
                recovered.append(run)
        except Exception as e:  # One bad thread must not stop the sweep of the others.
            log.exception("recovery_failed", thread=lease.thread_id, error=type(e).__name__)
    return recovered


async def sweep_forever(rt: Runtime, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await sweep_once(rt)
        except Exception as e:
            log.exception("sweep_failed", error=type(e).__name__)
