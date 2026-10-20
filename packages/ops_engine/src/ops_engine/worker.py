"""The worker loop: claims work, takes the run's thread lease, runs the compiled graph and records how it ended.

One claimed row is one pass over a run: a start runs it from its trigger (or continues from its last checkpoint after
a crash), a resume answers the review it waits on. While it runs, a heartbeat renews both the thread lease and the
work claim. A worker that dies leaves both to lapse; the next claim takes the row over with a higher lease generation
and LangGraph continues from the last checkpoint, where the node wrapper returns every recorded step without running
it. A pass that raises is retried; the third failure fails the run with its error (workflow-runner.md section 4).

The sweeper is this claim: a lapsed claim is what a crashed run looks like here. The v1 sweeper in the API process
leaves engine threads (RUN_PREFIX) alone.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from langgraph.types import Command

from ops_checkpointer import LeaseSupersededError
from ops_service_kit.logging import get_logger

from .compiler import CHANNEL, CompiledCache, WriteInDoubtError
from .definition import parse
from .journal import RunCancelledError
from .node_types import TypeRegistry
from .ports import EnginePorts, EventPort, LeaseBusyError, LeasePort
from .store import TERMINAL, DefinitionStore, RunStore, SqlJournal, Transactions, Work, WorkQueue
from .store.clock import now_iso

log = get_logger("ops_engine.worker")

MAX_PASSES = 3
# A write still in doubt after this many passes (backoff capped at 30 s, so about ten minutes) fails its run for a
# person to settle: the gateway expires a stale claim to lost well before, so this is reached only when it cannot.
MAX_DOUBT_PASSES = 20
RECURSION_LIMIT = 100


class ClaimLostError(RuntimeError):
    pass


# The review deadline when the host gives none: the workspace setting's own default.
DEFAULT_REVIEW_HOURS = 8.0


@dataclass
class WorkerHost:
    """What the host process (agents-service) hands the worker: its tenancy, ports and stores."""

    tx: Transactions
    registry: TypeRegistry
    ports: EnginePorts
    leases: LeasePort
    events: EventPort
    checkpointer: Any
    # Runs a claimed run's pass under the tenant its row names: the host's isolation context, entered with a named
    # reason, as its loops do for a claimed thread.
    run_scope: Callable[[str], AbstractContextManager[object]]
    owner: str
    concurrency: int = 4
    # Called with the run before its pass, inside the pass's own task: the host records the run's team, so what the
    # pass sends on (a tool call's service token) names the team the run belongs to, as a person's request would.
    enter_run: Callable[[dict[str, Any]], None] | None = None
    # The tenant's review deadline in hours, for a review step that sets none (the workspace's reviewSlaHours).
    review_hours: Callable[[], Awaitable[float]] | None = None
    # Records a reminder on a review still waiting (c-277), with the run and {node, iteration, n, title, openedAt,
    # waitedHours}: the host reports it as its `task.reminder` service event. None records only the run's own event.
    remind: Callable[[dict[str, Any], dict[str, Any]], Awaitable[None]] | None = None
    _cache: CompiledCache | None = field(default=None, init=False)

    def cache(self) -> CompiledCache:
        if self._cache is None:
            self._cache = CompiledCache(self.registry, self.ports, SqlJournal(self.tx), self.checkpointer)
        return self._cache


def config(run: dict[str, Any], generation: int | None) -> dict[str, Any]:
    configurable: dict[str, Any] = {"thread_id": run["id"], "run_id": run["id"], "engine_mode": run["mode"]}
    if generation is not None:
        configurable["lease_generation"] = generation
    return {"configurable": configurable, "recursion_limit": RECURSION_LIMIT}


def ending(values: dict[str, Any]) -> dict[str, Any] | None:
    """The End node's envelope among the final values, if the run reached one."""
    for key, env in values.items():
        if key.startswith(CHANNEL) and isinstance(env, dict):
            e = cast(dict[str, Any], env)
            out = e.get("out")
            if e.get("port") == "" and isinstance(out, dict) and "outcome" in out:
                return cast(dict[str, Any], out)
    return None


class Worker:
    def __init__(self, host: WorkerHost) -> None:
        self.host = host
        self.queue = WorkQueue(host.tx, host.owner, host.leases.ttl)
        self.runs = RunStore(host.tx)
        self.definitions = DefinitionStore(host.tx)

    async def run_forever(self, stop: asyncio.Event, poll: float) -> None:
        """Claims rows until `stop` is set, running up to `concurrency` passes at once."""
        slots = asyncio.Semaphore(self.host.concurrency)
        tasks: set[asyncio.Task[None]] = set()
        while not stop.is_set():
            await slots.acquire()
            try:
                work = await self.queue.claim()
            except Exception as e:  # A database blip must not end the worker; the next poll tries again.
                log.exception("engine_claim_failed", error=type(e).__name__)
                work = None
            if work is None:
                slots.release()
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), poll)
                continue

            async def one(w: Work = work) -> None:
                try:
                    await self.process(w)
                except Exception as e:  # One run's failure is recorded on the run; the loop goes on.
                    log.exception("engine_process_failed", work=w.id, error=type(e).__name__)
                finally:
                    slots.release()

            task = asyncio.create_task(one())
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        for t in list(tasks):
            t.cancel()

    async def work_once(self) -> bool:
        """Claims and processes one row; False when there was none. For tests and one-shot runs."""
        work = await self.queue.claim()
        if work is None:
            return False
        await self.process(work)
        return True

    async def process(self, work: Work) -> None:
        """Each pass runs in its own task under the row's tenant, so two runs of different tenants never share one."""

        async def scoped() -> None:
            with self.host.run_scope(work.tenant_id):
                await self._process(work)

        await asyncio.create_task(scoped())

    async def _process(self, work: Work) -> None:
        run = await self.runs.get(work.run_id)
        # A run whose graph reached its End is done with work, though it may still wait on runs it started: its
        # checkpoints are gone, so a late row (a decided review's deadline) must not start the graph again.
        if run is None or run["status"] in TERMINAL or run.get("outcome") is not None:
            await self.queue.done(work)
            return
        if self.host.enter_run is not None:
            self.host.enter_run(run)
        lease_run = f"work_{work.id}_{work.attempts}"
        try:
            generation = await self.host.leases.acquire(run["id"], lease_run)
        except LeaseBusyError:
            await self.queue.release(work, 1.0)
            return
        lost = asyncio.Event()
        beat = asyncio.create_task(self._heartbeat(work, run["id"], lease_run, lost))
        passing = asyncio.create_task(self._pass(work, run, generation))
        watching = asyncio.create_task(lost.wait())
        try:
            # A lost lease or claim stops the pass where it is: another worker owns the run from here, and every write
            # this one could still make is refused by the fence (checkpoints, run rows, events).
            await asyncio.wait({passing, watching}, return_when=asyncio.FIRST_COMPLETED)
            if not passing.done():
                passing.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await passing
                raise ClaimLostError("the lease or the work claim was taken over mid-pass")
            passing.result()
            await self.queue.done(work)
        except RunCancelledError as e:
            # The step under way when the run was cancelled ended and was recorded; the next one did not begin.
            log.info("engine_pass_cancelled", run=run["id"], work=work.id, error=str(e))
            await self.queue.done(work, error="run cancelled")
            await self._drop_checkpoints(run["id"])
        except (ClaimLostError, LeaseSupersededError) as e:
            log.warning("engine_claim_lost", run=run["id"], work=work.id, error=str(e))
        except WriteInDoubtError as e:
            # Whether the write happened is not known yet; never re-sent, the run is tried again later.
            log.warning("engine_write_in_doubt", run=run["id"], work=work.id, error=str(e))
            with suppress(LeaseSupersededError):
                if work.attempts > MAX_DOUBT_PASSES:
                    message = f"a write is still in doubt after {work.attempts} passes; a person must settle it: {e}"
                    await self.runs.update(
                        run["id"], generation=generation, status="failed", error=message, finished_at=now_iso()
                    )
                    await self._event(run, generation, "failed", None, {"message": message})
                    await self.queue.done(work, status="failed", error=message)
                    await self.runs.settle_parents(run)
                else:
                    await self.runs.update(run["id"], generation=generation, status="queued", error=str(e))
                    await self.queue.release(work, min(30.0, float(2**work.attempts)), error=str(e))
        except Exception as e:
            message = f"{type(e).__name__}: {e}"
            log.exception("engine_pass_failed", run=run["id"], work=work.id, attempt=work.attempts)
            with suppress(LeaseSupersededError):
                if work.attempts < MAX_PASSES:
                    await self.runs.update(run["id"], generation=generation, status="queued", error=message)
                    await self.queue.release(work, float(2 ** (work.attempts - 1)), error=message)
                else:
                    await self.runs.update(
                        run["id"], generation=generation, status="failed", error=message, finished_at=now_iso()
                    )
                    await self._event(run, generation, "failed", None, {"message": message})
                    await self.queue.done(work, status="failed", error=message)
                    await self._drop_checkpoints(run["id"])
                    await self.runs.settle_parents(run)
        finally:
            watching.cancel()
            beat.cancel()
            with suppress(asyncio.CancelledError):
                await beat
            await self.host.leases.release(run["id"], lease_run)

    async def _heartbeat(self, work: Work, thread_id: str, lease_run: str, lost: asyncio.Event) -> None:
        """Renews the lease and the claim. A cancel does not stop the pass here: the step under way finishes and is
        journaled, and the next step's journal row is refused (RunCancelledError), so no call is cut off mid-flight."""
        while True:
            await asyncio.sleep(self.host.leases.ttl / 3)
            if not await self.host.leases.heartbeat(thread_id, lease_run) or not await self.queue.renew(work):
                log.warning("engine_lease_lost", run=thread_id, work=work.id)
                lost.set()
                return

    async def _event(self, run: dict[str, Any], generation: int, type_: str, node: str | None, data: Any) -> None:
        await self.host.events.append(run["id"], run["team_id"], type_, node, data, generation=generation)

    async def _drop_checkpoints(self, run_id: str) -> None:
        """The journal is the record the console reads; an ended run's checkpoints are not needed. A failed delete
        leaves rows behind, which is logged, not fatal."""
        try:
            await self.host.checkpointer.adelete_thread(run_id)
        except Exception as e:
            log.exception("engine_checkpoints_not_deleted", run=run_id, error=type(e).__name__)

    async def _pass(self, work: Work, run: dict[str, Any], generation: int) -> None:
        stored = await self.definitions.get(run["workflow_id"], run["version"])
        if stored is None or stored["digest"] != run["digest"]:
            raise RuntimeError(f"{run['workflow_id']} version {run['version']} is missing or changed under its digest")
        graph = self.host.cache().get(parse(cast(dict[str, Any], stored["definition"])))
        cfg = config(run, generation)
        saver = self.host.checkpointer
        if hasattr(saver, "araise_fence"):
            # Before the first read: a stalled previous owner's checkpoint writes are refused from here on.
            await saver.araise_fence(run["id"], generation)
        snap = await graph.aget_state(cfg)
        graph_input: Any
        if not snap.created_at:
            graph_input = {"input": run["input"]}
        elif snap.interrupts:
            waiting = snap.interrupts[0]
            if work.kind == "remind":
                # Never a resume: the review keeps waiting, so the graph does not run and the run stays as it is.
                await self._remind(run, generation, work, waiting)
                return
            if work.kind not in ("resume", "timeout"):
                await self._waiting(run, generation, waiting)  # a start that reached its review before a crash
                return
            meant = cast(dict[str, Any], work.payload or {}).get("interruptId")
            asked = cast(dict[str, Any], work.payload or {})
            here = cast(dict[str, Any], waiting.value or {})
            other_step = asked.get("node") is not None and asked.get("node") != here.get("node")
            other_pass = asked.get("iteration") is not None and asked.get("iteration") != here.get("iteration")
            if (meant is not None and meant != waiting.id) or other_step or other_pass:
                # Meant for a review the run has left (decided, or timed out first), or for a step it no longer waits
                # at: resuming would decide the next pause.
                log.info("engine_resume_stale", run=run["id"], kind=work.kind)
                return
            graph_input = Command(resume=cast(dict[str, Any], work.payload or {}).get("resume"))
        elif work.kind in ("timeout", "remind"):
            return  # the review was decided before its deadline or its reminder
        elif snap.next:
            graph_input = None  # continue from the last checkpoint
        else:
            await self._finished(run, generation, graph, cfg)
            return
        await self.runs.update(run["id"], generation=generation, status="running", waiting=None)
        await self.runs.settle_parents(run)
        await self._event(
            run, generation, "started", None, {"kind": work.kind, "owner": self.host.owner, "generation": generation}
        )
        steps = graph.astream(graph_input, cfg, stream_mode=["tasks", "updates"], durability="sync")
        async for mode, chunk in steps:
            if mode == "tasks":
                phase = "end" if "result" in chunk else "start"
                data: dict[str, Any] = {"phase": phase}
                if phase == "end":
                    data["error"] = chunk.get("error") is not None
                await self._event(run, generation, "node", chunk["name"], data)
        snap = await graph.aget_state(cfg)
        if snap.interrupts:
            await self._waiting(run, generation, snap.interrupts[0])
        else:
            await self._finished(run, generation, graph, cfg)

    async def _waiting(self, run: dict[str, Any], generation: int, interrupt: Any) -> None:
        payload = cast(dict[str, Any], interrupt.value)
        node = str(payload.get("node"))
        iteration = int(payload.get("iteration") or 1)
        waiting = {"node": node, "iteration": iteration, "interruptId": interrupt.id, "payload": payload}
        await self.runs.update(run["id"], generation=generation, status="waiting", waiting=waiting)
        await self.runs.settle_parents(run)
        await self._event(run, generation, "waiting_review", node, {"payload": payload})
        if payload.get("wakeAfterSeconds"):
            # A step paused for a time (Wait, c-277; Run workflow's timeout, c-263) is woken by delayed work, queued
            # once per step and iteration at the first pause: later pauses of the same step find it.
            await self.queue.enqueue(
                run["id"],
                "timeout",
                f"timeout:{run['id']}:{node}:{iteration}",
                {"resume": {"timeout": True}, "node": node, "iteration": iteration},
                after_seconds=float(payload["wakeAfterSeconds"]),
            )
        if payload.get("remindEveryHours"):
            await self._next_reminder(run, payload, interrupt.id, 1)
        if payload.get("onTimeout") == "expire":
            hours = payload.get("slaHours")
            if hours is None:
                hours = await self.host.review_hours() if self.host.review_hours is not None else DEFAULT_REVIEW_HOURS
            resume = {"decision": "timeout", "by": "system:sla", "reason": "No decision before the deadline"}
            await self.queue.enqueue(
                run["id"],
                "timeout",
                f"timeout:{run['id']}:{node}:{iteration}",
                {"resume": resume, "interruptId": interrupt.id},
                after_seconds=float(hours) * 3600,
            )

    async def _next_reminder(self, run: dict[str, Any], payload: dict[str, Any], interrupt_id: str, n: int) -> None:
        """Queues reminder `n` of a waiting review, keyed by it, so a pause found again queues none twice."""
        node, iteration = str(payload.get("node")), int(payload.get("iteration") or 1)
        await self.queue.enqueue(
            run["id"],
            "remind",
            f"remind:{run['id']}:{node}:{iteration}:{n}",
            {"interruptId": interrupt_id, "node": node, "n": n},
            after_seconds=float(payload["remindEveryHours"]) * 3600 * n - self._waited(payload),
        )

    @staticmethod
    def _waited(payload: dict[str, Any]) -> float:
        """Seconds since the review opened, by its `openedAt`; 0 when it has none."""
        opened = payload.get("openedAt")
        if not isinstance(opened, str):
            return 0.0
        at = datetime.fromisoformat(opened.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(UTC) - at).total_seconds())

    async def _remind(self, run: dict[str, Any], generation: int, work: Work, interrupt: Any) -> None:
        """A reminder falls due: recorded when the run still waits at the same review, then the next one queued. A
        review decided since, or a later pause, takes no reminder and queues none."""
        asked = cast(dict[str, Any], work.payload or {})
        if asked.get("interruptId") != interrupt.id:
            return
        payload = cast(dict[str, Any], interrupt.value)
        n = int(asked.get("n") or 1)
        node = str(payload.get("node"))
        reminder: dict[str, Any] = {
            "node": node,
            "iteration": int(payload.get("iteration") or 1),
            "n": n,
            "title": payload.get("title"),
            "openedAt": payload.get("openedAt"),
            "waitedHours": round(self._waited(payload) / 3600, 2),
        }
        await self._event(run, generation, "reminded", node, reminder)
        if self.host.remind is not None:
            await self.host.remind(run, reminder)
        await self._next_reminder(run, payload, interrupt.id, n + 1)

    async def _finished(self, run: dict[str, Any], generation: int, graph: Any, cfg: dict[str, Any]) -> None:
        values = cast(dict[str, Any], (await graph.aget_state(cfg)).values or {})
        end = ending(values) or {}
        outcome = str(end.get("outcome") or "done")
        failed = end.get("result") == "failed"
        status = await self.runs.finish(
            run["id"],
            generation=generation,
            failed=failed,
            outcome=outcome,
            output=end.get("output"),
            error=f"Ended at {end.get('name')}, an end marked as a failure" if failed else None,
        )
        await self._event(run, generation, "finished", None, {"outcome": outcome, "status": status})
        await self._drop_checkpoints(run["id"])
        await self.runs.settle_parents(run)
