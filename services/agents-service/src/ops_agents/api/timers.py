"""Durable timers for human steps: the SLA clock LangGraph does not have (agents-service, worker process type).

When a run ends waiting on a human step whose interrupt carries an `sla` block, `sync_timers` writes its timers
(warn, breach, maxWait) and cancels the timers of interrupts no longer waiting. The `timers` table is the source of
truth. `fire(thread, timer)` is the only way a timer fires (ADR-0016): the internal route
`POST /v1/threads/{id}/timers/{timerId}/fire` calls it, and so does the PostgreSQL poller, the one scheduler shipped.
Any later scheduler (pg_cron, a cloud scheduler, Temporal) only wakes the same route.

`fire` is idempotent on the timer id and safe to call early, twice or concurrently. Under the thread's lease it
re-checks that the timer is due, not cancelled, not already fired, and that its interrupt and round still wait. It
then claims the timer with the lease generation it holds. A breach or max wait resumes the thread with a timeout
decision through `runs.execute`, and `fired_at` is written, fenced by that generation, once the step has taken the
decision into its checkpoint. A fire that dies before then leaves the timer claimed but not fired, and the next fire
under a newer generation claims it again. After `MAX_ATTEMPTS` claims the timer is set aside for a person.

Due times are the database's clock (`now()`), as are leases since E2b, so every process agrees on what is due.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Literal, cast

from langgraph.types import Command

from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.logging import get_logger

from ..store.leases import LeaseHeldError
from ..store.timers import TimerStore, Wanted, key_of
from .deps import Runtime
from .runs import config, execute, graph_store, pending, resolve
from .tenant_tasks import as_thread_tenant

log = get_logger("ops_agents.api.timers")

MAX_ATTEMPTS = 3


def store_of(rt: Runtime) -> TimerStore:
    return TimerStore(graph_store(rt).engine)


def _wanted(waiting: list[dict[str, Any]]) -> Wanted:
    """(timer key, kind) -> (node, interrupt id, delay) for every timer the waiting interrupts call for. Warn and
    breach belong to one interrupt, so a re-raised interrupt (reassign, escalate) gets a fresh clock; max wait
    belongs to the step's review, so it keeps running across re-raises."""
    out: Wanted = {}
    for w in waiting:
        p: dict[str, Any] = w["payload"]
        sla: dict[str, Any] = p["sla"]
        node = str(p.get("node") or "human")
        # LangGraph gives every interrupt a node raises in one task the same id, so a re-raised review (reassign,
        # escalate) is told apart by its round.
        clock = round_key(w["id"], sla.get("round", 0))
        if sla.get("warnAtSeconds") is not None:
            out[(clock, "warn")] = (node, w["id"], float(sla["warnAtSeconds"]))
        if sla.get("slaSeconds") is not None:
            out[(clock, "breach")] = (node, w["id"], float(sla["slaSeconds"]))
        if sla.get("maxWaitSeconds") is not None:
            out[(f"{node}:{p.get('review_id', '')}", "maxWait")] = (node, None, float(sla["maxWaitSeconds"]))
    return out


def round_key(interrupt_id: str, round_: Any) -> str:
    # URL-safe: timer ids are path segments of the fire endpoint.
    return f"{interrupt_id}.r{int(round_)}"


def _key(row: Any) -> tuple[str, str]:
    """A timer id is `<interrupt or review>:<kind>:<n>`; n counts restarts by customer replies."""
    return key_of(row)


async def waiting_with_sla(rt: Runtime, thread_id: str) -> list[dict[str, Any]]:
    _, graph = await resolve(rt, thread_id)
    snap = await graph.aget_state(config(thread_id))
    out: list[dict[str, Any]] = []
    for w in pending(snap):
        payload: Any = w["payload"]
        if isinstance(payload, dict) and cast(dict[str, Any], payload).get("sla"):
            out.append(w)
    return out


async def sync_timers(rt: Runtime, thread_id: str, *, generation: int | None = None) -> None:
    """Brings the thread's timers in line with what it is waiting on. Rows another poller holds are skipped: that
    poller is firing them and will write the outcome. Timers need PostgreSQL (`now()`, `SKIP LOCKED`); on another
    database, as in the SQLite unit tests, there are none."""
    store = store_of(rt)
    if not store.enabled:
        return
    wanted = _wanted(await waiting_with_sla(rt, thread_id))
    cancelled, armed = await store.sync(thread_id, wanted, generation)
    for timer_id in cancelled:
        await rt.timer_scheduler.cancel(thread_id, timer_id)
    for timer_id, due_at in armed:
        await rt.timer_scheduler.schedule(thread_id, timer_id, due_at)


async def sla_view(rt: Runtime, thread_id: str) -> dict[str, Any] | None:
    """The thread's timers and SLA events for GET state; None where timers are not kept (non-PostgreSQL)."""
    timer_store = store_of(rt)
    if not timer_store.enabled:
        return None
    rows = await timer_store.rows(thread_id)
    events = [e for r in await graph_store(rt).runs(thread_id) if r["kind"] == "sla" for e in r["events"]]

    def at(v: Any) -> str | None:
        return v.isoformat() if v is not None else None

    return {
        "timers": [
            {
                "timerId": r.timer_id,
                "kind": r.kind,
                "node": r.node,
                "dueAt": at(r.due_at),
                "firedAt": at(r.fired_at),
                "cancelledAt": at(r.cancelled_at),
                "attempts": r.attempts,
                "state": "fired"
                if r.fired_at
                else "cancelled"
                if r.cancelled_at
                else "failed"
                if r.failed_at
                else "open",
            }
            for r in rows
        ],
        "events": [{"event": e["event"], "data": e.get("data")} for e in events],
    }


async def restart_on_customer_reply(rt: Runtime, thread_id: str) -> list[dict[str, Any]]:
    """A customer reply restarts the clock: the open warn and breach timers are cancelled and re-armed from now.
    The max wait keeps running, so a conversation that never ends still times out."""
    waiting = await waiting_with_sla(rt, thread_id)
    wanted = {k: v for k, v in _wanted(waiting).items() if k[1] != "maxWait"}
    restarted = [
        {"timerId": timer_id, "kind": kind, "dueAt": due_at.isoformat()}
        for timer_id, kind, due_at in await store_of(rt).restart(thread_id, wanted)
    ]
    await journal(
        rt, thread_id, [{"event": "sla.restarted", "data": {"reason": "customer_reply", "timers": restarted}}]
    )
    return restarted


async def journal(rt: Runtime, thread_id: str, events: list[dict[str, Any]], *, generation: int | None = None) -> None:
    """SLA events as a run row of kind `sla`, so GET /runs and the state view show them in order with the runs."""
    store = graph_store(rt)
    run_id = new_id("run")
    await store.start_run(
        run_id, thread_id, "sla", now_iso(), {"sla": [e["event"] for e in events]}, generation=generation
    )
    await store.finish_run(
        run_id,
        "done",
        [{**e, "runId": run_id, "seq": i} for i, e in enumerate(events)],
        now_iso(),
        generation=generation,
    )


def _events_for(kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    sla: dict[str, Any] = payload["sla"]
    base = {"group": sla["group"], "round": sla["round"], "node": payload.get("node")}
    if kind == "warn":
        return [{"event": "sla.warn", "data": base}]
    if kind == "maxWait":
        return [{"event": "sla.max_wait", "data": {**base, "outcome": "rejected"}}]
    events: list[dict[str, Any]] = [{"event": "sla.breach", "data": base}]
    action = sla["onTimeout"]
    if action == "escalate" and not sla["escalated"]:
        events.append({"event": "sla.escalated", "data": {**base, "to": sla.get("escalateTo")}})
    elif action == "reassign":
        events.append({"event": "sla.reassigned", "data": {**base, "to": sla.get("reassignTo")}})
    else:
        events.append({"event": "sla.timeout", "data": {**base, "outcome": "rejected"}})
    return events


Hook = Callable[[], Coroutine[Any, Any, None]]

FireStatus = Literal["fired", "duplicate", "not_due", "not_waiting", "busy", "cancelled", "failed", "unknown", "retry"]
# Statuses a caller must treat as a refusal (409 on the route): the timer will never fire.
REFUSED: frozenset[str] = frozenset({"cancelled", "failed", "unknown"})


@dataclass(frozen=True)
class FireResult:
    status: FireStatus
    timer_id: str
    run_id: str | None = None
    attempts: int | None = None


def _matching(row: Any, waiting: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The waiting interrupt this timer belongs to: by interrupt and round for warn and breach, by node for max
    wait."""
    for w in waiting:
        if row.interrupt_id:
            if round_key(w["id"], w["payload"]["sla"].get("round", 0)) == _key(row)[0]:
                return w
        elif w["payload"].get("node") == row.node:
            return w
    return None


async def fire(rt: Runtime, thread_id: str, timer_id: str, *, after_accept: Hook | None = None) -> FireResult:
    """Fires one timer if, and only if, it should fire now. See the module docstring for the contract."""
    timer_store = store_of(rt)
    row = await timer_store.get(thread_id, timer_id)
    if row is None:
        return FireResult("unknown", timer_id)
    if row.fired_at is not None:
        return FireResult("duplicate", timer_id, attempts=row.attempts)
    if row.cancelled_at is not None:
        return FireResult("cancelled", timer_id)
    if row.failed_at is not None:
        return FireResult("failed", timer_id, attempts=row.attempts)
    if not row.is_due:
        # An early wake-up from a scheduler whose clock runs ahead: nothing happens, and the timer stays armed.
        return FireResult("not_due", timer_id)
    if row.kind == "warn":
        return await _fire_warning(rt, row)
    assert rt.leases is not None
    run_id = new_id("run")
    try:
        generation = await rt.leases.acquire(thread_id, run_id)
    except LeaseHeldError:
        # The thread is running. The timer stays due; the run either decides the step (and sync cancels the timer)
        # or leaves it waiting, and the next fire goes ahead.
        return FireResult("busy", timer_id)
    # Every early return below releases the lease, and only after its transaction has closed: an open transaction
    # holds the fence's share lock on the lease row, and the release's update would wait on it forever. An exception
    # does not release: like a crash, it leaves the lease to expire and E2's sweeper continues the thread.
    match = _matching(row, await waiting_with_sla(rt, thread_id))
    claim = await timer_store.claim(thread_id, timer_id, generation, waiting=match is not None)
    if claim.outcome != "claimed":
        await rt.leases.release(thread_id, run_id)
        return FireResult(claim.outcome, timer_id)
    row = claim.row
    assert match is not None, "checked in the claim transaction"
    attempts = claim.attempts
    if attempts > MAX_ATTEMPTS:
        await timer_store.close(row, generation, "failed")
        data = {"timerId": timer_id, "attempts": attempts - 1, "error": await _last_error(rt, thread_id)}
        await journal(rt, thread_id, [{"event": "sla.fire_failed", "data": data}], generation=generation)
        await rt.leases.release(thread_id, run_id)
        log.warning("timer_failed", thread=thread_id, timer=timer_id, attempts=attempts - 1)
        return FireResult("failed", timer_id, attempts=attempts - 1)
    store = graph_store(rt)
    decision = {"decision": "timeout", "timer": row.kind, "timerId": timer_id}
    if not await store.start_run(run_id, thread_id, "timer", now_iso(), {"resume": decision}, generation=generation):
        await rt.leases.release(thread_id, run_id)
        return FireResult("busy", timer_id)
    await store.set_thread_status(thread_id, "busy", now_iso(), generation=generation)
    if after_accept is not None:
        await after_accept()
    thread_row, graph = await resolve(rt, thread_id)
    events = _events_for(row.kind, match["payload"])
    accepted = False
    # From here execute owns the lease and releases it at the end.
    async for e in execute(rt, thread_row, graph, graph_input=Command(resume=decision), run_id=run_id, kind="timer"):
        data: dict[str, Any] = e.get("data") or {}
        done = e["event"] == "node_end" and e.get("node") == row.node and not data.get("error")
        if not accepted and done:
            # The step has taken the timeout into its checkpoint: from here a crash continues the run, it does
            # not fire again. The mark is fenced: a fire whose lease was taken over cannot write it.
            accepted = await timer_store.close(row, generation, "fired", owner=rt.leases.owner)
            if accepted:
                await journal(rt, thread_id, events, generation=generation)
    log.info("timer_fire", thread=thread_id, timer=timer_id, accepted=accepted, run=run_id)
    return FireResult("fired" if accepted else "retry", timer_id, run_id=run_id, attempts=attempts)


async def _last_error(rt: Runtime, thread_id: str) -> str | None:
    """The error the last failed timer run ended with, so the person handling the set-aside timer sees why."""
    for r in reversed(await graph_store(rt).runs(thread_id)):
        if r["kind"] == "timer" and r["status"] == "error":
            events: list[dict[str, Any]] = r["events"]
            errors = [e for e in events if e.get("event") == "error"]
            last: dict[str, Any] = (errors[-1].get("data") or {}) if errors else {}
            return str(last.get("message")) if errors else None
    return None


async def _fire_warning(rt: Runtime, row: Any) -> FireResult:
    """A warning resumes nothing, so it takes no lease: one conditional update decides who journals it."""
    match = _matching(row, await waiting_with_sla(rt, row.thread_id))
    timer_store = store_of(rt)
    if match is None:
        await timer_store.close(row, None, "cancelled")
        return FireResult("not_waiting", row.timer_id)
    if not await timer_store.close(row, None, "fired", owner="warn"):
        return FireResult("duplicate", row.timer_id)
    await journal(rt, row.thread_id, _events_for("warn", match["payload"]))
    return FireResult("fired", row.timer_id)


class TimerPoller:
    """The PostgreSQL scheduler: finds due timers and calls `fire` for each. It holds no lock and decides nothing;
    two pollers calling `fire` on one timer get one `fired` and one `busy` or `duplicate`."""

    def __init__(self, rt: Runtime, *, after_accept: Hook | None = None) -> None:
        self.rt = rt
        # Tests only: runs after the resume is journaled and before the graph runs, to kill the fire there.
        self.after_accept = after_accept

    async def poll_once(self, limit: int = 10) -> list[str]:
        """Fires up to `limit` due timers. Returns the ids that fired."""
        fired: list[str] = []
        for thread_id, timer_id in await store_of(self.rt).due(limit):
            result = await as_thread_tenant(
                self.rt,
                thread_id,
                lambda thread_id=thread_id, timer_id=timer_id: fire(
                    self.rt, thread_id, timer_id, after_accept=self.after_accept
                ),
            )
            if result is not None and result.status == "fired":
                fired.append(result.timer_id)
        return fired


async def poll_forever(rt: Runtime, interval: float) -> None:
    poller = TimerPoller(rt)
    while True:
        try:
            await poller.poll_once()
        except Exception as e:  # A bad timer must not stop the poller; it stays due and is retried next time.
            log.exception("timer_poll_failed", error=type(e).__name__)
        await asyncio.sleep(interval)
