"""Running a graph on a thread, shared by the streaming route and the sweeper: one code path for the lease
heartbeat, the journal and the event shape `{event, runId, seq, node?, data?}`."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import Any, cast

from ops_agents.graphs.definition import ROUTE_NODE, WorkflowDefinition
from ops_checkpointer import LeaseSupersededError
from ops_service_kit.errors import ApiError, Conflict, NotFound
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger

from ..store.events import EventLog
from ..store.graphs import GraphStore
from ..store.leases import Heartbeat, Leases
from .deps import Runtime
from .event_log import designed_type

log = get_logger("ops_agents.api.runs")

# Fan-out across attachments runs at most this many tasks at once (LangGraph's own concurrency limit).
MAX_CONCURRENCY = 4
RECURSION_LIMIT = 60


class GraphsUnavailable(ApiError):
    status = 503
    code = "model_unavailable"


class LeaseLostError(RuntimeError):
    pass


def graph_store(rt: Runtime) -> GraphStore:
    """The threads, runs and versions as stored rows. Reading them needs no model, so a list or a queue loads with
    none configured; running or resuming a graph asks `require_graphs` first."""
    if rt.graph_store is None:
        raise GraphsUnavailable(rt.model_error or "Graphs are not available: no model is configured.")
    return rt.graph_store


def require_graphs(rt: Runtime) -> Leases:
    """The leases a run holds, when the graph runtime is up; 503 model_unavailable when no model is configured, so a
    route that runs or resumes a graph refuses before it starts."""
    if not rt.graphs or rt.leases is None:
        raise GraphsUnavailable(rt.model_error or "Graphs are not available: no model is configured.")
    return rt.leases


def config(thread_id: str, generation: int | None = None, run_id: str | None = None) -> dict[str, Any]:
    """`generation` is the run's lease generation; every checkpoint and gateway write of the run carries it (E2b).
    `run_id` lets each usage row name the run that spent it (E12)."""
    configurable: dict[str, Any] = {"thread_id": thread_id}
    if generation is not None:
        configurable["lease_generation"] = generation
    if run_id is not None:
        configurable["run_id"] = run_id
    return {
        "configurable": configurable,
        "max_concurrency": MAX_CONCURRENCY,
        "recursion_limit": RECURSION_LIMIT,
    }


def pending(snapshot: Any) -> list[dict[str, Any]]:
    return [{"id": i.id, "payload": i.value} for i in getattr(snapshot, "interrupts", ())]


async def definition(rt: Runtime, name: str, version: int) -> WorkflowDefinition:
    stored = await graph_store(rt).version(name, version)
    if stored is None:
        raise NotFound(f"{name} version {version}")
    return WorkflowDefinition.model_validate(stored["definition"])


async def resolve(rt: Runtime, thread_id: str) -> tuple[dict[str, Any], Any]:
    """The thread and the graph it runs on: a code graph by name, or its pinned workflow version compiled from JSON."""
    row = await graph_store(rt).thread(thread_id)
    if row is None:
        # Another tenant's or team's thread is not found either: the store and the database never return it (c-429).
        raise NotFound("Thread")
    require_graphs(rt)
    if row["graph"] in rt.graphs:
        return row, rt.graphs[row["graph"]]
    d = await definition(rt, row["graph"], row["version"])
    if d.digest() != row["digest"]:
        raise Conflict(
            f"Stored {row['graph']} version {row['version']} no longer matches the thread's digest.",
            code="digest_mismatch",
        )
    assert rt.workflows is not None
    return row, rt.workflows.get(d)


async def execute(
    rt: Runtime, row: dict[str, Any], graph: Any, *, graph_input: Any, run_id: str, kind: str
) -> AsyncGenerator[dict[str, Any]]:
    """`_execute`, with each event written to the thread event log before it is yielded, so a client re-attaching
    mid-run, and a crash, see every event the stream has sent.

    On SQLite (tests and local runs) the events are written when the run ends instead: its engine shares one
    connection, and a write from this consumer would interleave with a node's own writes running in LangGraph's tasks
    and lose one of them."""
    engine = graph_store(rt).engine
    deferred: list[dict[str, Any]] | None = [] if engine.dialect.name == "sqlite" else None

    async def write(e: dict[str, Any]) -> None:
        type_ = designed_type(e)
        if type_ is None:
            return
        try:
            await EventLog(engine).append(
                thread_id=row["id"],
                team_id=row["team_id"],
                run_id=run_id,
                type_=type_,
                node=e.get("node"),
                data=e.get("data"),
            )
        except Exception as exc:  # A lost log write must not stop the run; the journal still records the event.
            log.exception("event_log_append_failed", thread=row["id"], run=run_id, error=type(exc).__name__)

    finished = False
    try:
        async for e in _execute(rt, row, graph, graph_input=graph_input, run_id=run_id, kind=kind):
            if deferred is None:
                await write(e)
            else:
                deferred.append(e)
            if e["event"] == "end":
                finished = cast(dict[str, Any], e.get("data") or {}).get("status") == "done"
            yield e
    finally:
        for e in deferred or []:
            await write(e)
    if finished and cast(dict[str, Any], row.get("meta") or {}).get("startedBy") in ("agent", "workflow"):
        from .child_runs import tell_parent  # noqa: PLC0415 - child_runs imports this module

        await tell_parent(rt, row)


async def _execute(
    rt: Runtime, row: dict[str, Any], graph: Any, *, graph_input: Any, run_id: str, kind: str
) -> AsyncIterator[dict[str, Any]]:
    """Runs the graph on the thread while holding its lease (already taken by the caller), and releases it at the end.
    If another owner takes the lease over mid-run, the run stops and the lease is left to its new owner."""
    store, leases = graph_store(rt), rt.leases
    assert leases is not None
    thread_id = row["id"]
    events: list[dict[str, Any]] = []
    status = "error"
    heartbeat = Heartbeat(leases, thread_id, run_id)
    heartbeat.start()
    generation = await leases.generation_of(thread_id, run_id)

    def event(name: str, node: str | None = None, data: Any = None) -> dict[str, Any]:
        e: dict[str, Any] = {"event": name, "runId": run_id, "seq": len(events)}
        if node is not None:
            e["node"] = node
        if data is not None:
            e["data"] = data
        events.append(e)
        return e

    try:
        yield event(
            "run_start", data={"graph": row["graph"], "kind": kind, "owner": leases.owner, "generation": generation}
        )
        if generation is not None and rt.saver is not None and hasattr(rt.saver, "araise_fence"):
            # Before the first read: from here on a stalled previous owner's checkpoint writes are refused.
            await rt.saver.araise_fence(thread_id, generation)
        # R9: a thread routed to people stops at the next step that ends with no write in flight.
        from .routing import WRITE_KINDS, mark_route_applied, plan_kinds, remaining, requested_route  # noqa: PLC0415

        plan = await plan_kinds(rt, row)
        route = await requested_route(rt, thread_id) if plan is not None else None

        async def stream(graph_input: Any, *, stop_for_route: bool) -> AsyncIterator[dict[str, Any]]:
            nonlocal route
            in_flight: set[str] = set()
            steps = graph.astream(
                graph_input,
                config(thread_id, generation, run_id),
                stream_mode=["tasks", "custom", "updates"],
                # LangGraph's default ("async") saves a step's checkpoint while the next step already runs, so a
                # refused write from a superseded owner would not stop its next step (and that step's model and
                # tool calls). "sync" saves before the next step starts: a refusal stops the stale owner there.
                durability="sync",
            )
            # Closed explicitly: leaving early for a route cancels in-flight reads here, not whenever it is collected.
            async with aclosing(steps):
                async for mode, chunk in steps:
                    if heartbeat.lost.is_set():
                        raise LeaseLostError("Another process took over this thread's lease; this run stopped.")
                    if mode == "tasks":
                        if "result" in chunk:
                            in_flight.discard(chunk["name"])
                            # LangGraph reports a task that raised with a `result` key too, so the error is carried.
                            yield event(
                                "node_end",
                                chunk["name"],
                                {"interrupted": bool(chunk.get("interrupts")), "error": chunk.get("error") is not None},
                            )
                            writing = plan is not None and any(plan.get(n) in WRITE_KINDS for n in in_flight)
                            if stop_for_route and plan is not None and not writing:
                                route = await requested_route(rt, thread_id)
                                if route is not None:
                                    return
                        else:
                            in_flight.add(chunk["name"])
                            yield event("node_start", chunk["name"])
                    elif mode == "custom":
                        yield event(chunk["event"], chunk.get("node"), chunk.get("data"))
                    elif mode == "updates" and "__interrupt__" in chunk:
                        for i in chunk["__interrupt__"]:
                            yield event("interrupt", data={"id": i.id, "payload": i.value})

        if route is None:
            async for e in stream(graph_input, stop_for_route=True):
                yield e
        if route is not None and plan is not None:
            values = (await graph.aget_state(config(thread_id))).values
            skipped = remaining(plan, values)
            yield event("route.skipped", data={"reason": route.get("reason"), "by": route.get("by"), "nodes": skipped})
            await graph.aupdate_state(
                config(thread_id, generation), {"route_reason": route.get("reason")}, as_node=ROUTE_NODE
            )
            await mark_route_applied(rt, thread_id, run_id)
            async for e in stream(None, stop_for_route=False):
                yield e
        after = await graph.aget_state(config(thread_id))
        status = "interrupted" if pending(after) else "done"
        yield event("end", data={"status": status})
    except (LeaseLostError, LeaseSupersededError) as e:
        status = "lease_lost"
        yield event("error", data={"message": str(e)})
    except Exception as e:  # The run's error is the stream's last event; the checkpoint keeps the last good step.
        status = "error"
        yield event("error", data={"message": f"{type(e).__name__}: {e}"})
    finally:
        await heartbeat.stop()
        await store.finish_run(run_id, status, events, now_iso(), generation=generation)
        if status != "lease_lost":
            try:
                await store.set_thread_status(
                    thread_id,
                    {"done": "idle", "interrupted": "interrupted"}.get(status, "error"),
                    now_iso(),
                    generation=generation,
                )
            except LeaseSupersededError:
                # Superseded at the very end: the new owner's journal and timers stand, and this run lets go.
                status = "lease_lost"
        if status != "lease_lost":
            # Before the lease goes, so a poller cannot resume the thread against timers not yet written.
            from .timers import sync_timers  # noqa: PLC0415 - timers.py imports this module

            try:
                await sync_timers(rt, thread_id, generation=generation)
            except Exception as e:  # The lease must still be released; a missed timer write is logged, not fatal.
                log.exception("timer_sync_failed", thread=thread_id, error=type(e).__name__)
            await leases.release(thread_id, run_id)
            # Replies that arrived on a channel while this run held the thread are delivered now, in order (E6).
            from .channels.inbox import drain  # noqa: PLC0415 - channels.inbox imports this module

            try:
                await drain(rt, thread_id)
            except Exception as e:  # The run is over either way; a missed delivery is retried by the next drain.
                log.exception("inbox_drain_failed", thread=thread_id, error=type(e).__name__)
