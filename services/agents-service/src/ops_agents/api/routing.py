"""R9, route remaining steps to people (spec interpreter-and-nodes §4.5), on the LangGraph adapter.

A request sets a flag on the thread (`graph_threads.meta.routeToPeople`). `runs.execute` reads it before it starts
and after every step that ends with no write step in flight, so an in-flight write always finishes and in-flight
reads are cancelled when the stream closes. It then journals the steps that will not run as `route.skipped`, writes
the routing through the workflow's built-in `route_to_people` node, and continues the thread to its built-in
`manual_handling` step, which waits for a person with the reason. A thread that is waiting or idle is routed at once
under its lease. Only definition workflows can be routed: code graphs have no plan to skip steps of.
"""

from __future__ import annotations

from typing import Any, cast

from ops_agents.graphs.definition import BUILT_IN_NODES
from ops_service_kit.errors import Conflict
from ops_service_kit.ids import new_id, now_iso

from ..store.leases import LeaseHeldError
from .deps import Runtime
from .runs import definition, execute, graph_store, resolve

FLAG = "routeToPeople"
# Node kinds whose step has a side effect outside the Runtime; routing waits for one in flight to finish.
WRITE_KINDS = frozenset({"tool"})
# Thread statuses with work left to route.
OPEN_STATUSES = ("idle", "busy", "interrupted", "error")


async def plan_kinds(rt: Runtime, row: dict[str, Any]) -> dict[str, str] | None:
    """Node id to kind for a definition workflow's pinned version; None for a code graph."""
    if row["graph"] in rt.graphs or row.get("version") is None:
        return None
    d = await definition(rt, row["graph"], row["version"])
    return {n.id: n.kind for n in d.nodes}


async def _meta(rt: Runtime, thread_id: str) -> dict[str, Any]:
    return await graph_store(rt).meta(thread_id)


async def _set_flag(rt: Runtime, thread_id: str, value: dict[str, Any]) -> None:
    await graph_store(rt).merge_meta(thread_id, {FLAG: value}, lock=True)


async def requested_route(rt: Runtime, thread_id: str) -> dict[str, Any] | None:
    """The thread's routing request if one is waiting to be applied."""
    route: Any = (await _meta(rt, thread_id)).get(FLAG)
    if not isinstance(route, dict):
        return None
    found = cast(dict[str, Any], route)
    return None if found.get("appliedBy") else dict(found)


async def mark_route_applied(rt: Runtime, thread_id: str, run_id: str) -> None:
    route = await requested_route(rt, thread_id) or {}
    await _set_flag(rt, thread_id, {**route, "appliedBy": run_id, "appliedAt": now_iso()})


def remaining(plan: dict[str, str], values: dict[str, Any]) -> list[str]:
    """The plan's steps that have not run on this thread, in plan order: the ones routing skips."""
    visited: list[Any] = values.get("visited") or []
    ran = {str(v).split("@", 1)[0] for v in visited}
    return [n for n in plan if n not in ran and n not in BUILT_IN_NODES]


async def route_thread(rt: Runtime, thread_id: str, reason: str, by: str) -> str:
    """Routes one thread. "routed" when it was applied now; "pending" when a run holds the thread and will apply
    it at its next step boundary with no write in flight; "finished" when the thread has no step left."""
    row, graph = await resolve(rt, thread_id)
    if await plan_kinds(rt, row) is None:
        raise Conflict("Only a definition workflow can be routed to people.", code="not_routable")
    snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    if snapshot.created_at and not snapshot.next:
        return "finished"  # nothing left to route
    await _set_flag(rt, thread_id, {"reason": reason, "by": by, "requestedAt": now_iso()})
    assert rt.leases is not None
    run_id = new_id("run")
    try:
        generation = await rt.leases.acquire(thread_id, run_id)
    except LeaseHeldError:
        return "pending"
    store = graph_store(rt)
    if not await store.start_run(run_id, thread_id, "route", now_iso(), {"route": reason}, generation=generation):
        await rt.leases.release(thread_id, run_id)
        return "pending"
    await store.set_thread_status(thread_id, "busy", now_iso(), generation=generation)
    async for _ in execute(rt, row, graph, graph_input=None, run_id=run_id, kind="route"):
        pass
    return "routed"


async def open_threads(rt: Runtime, workflow: str, version: int) -> list[str]:
    return await graph_store(rt).thread_ids(workflow, version, OPEN_STATUSES)
