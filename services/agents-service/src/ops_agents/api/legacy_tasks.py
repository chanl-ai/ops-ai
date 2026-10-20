"""Reviews opened before their workflow's review step named a task type (c-288; tick 31's design check found every open
task on the shared stack drawn the old way). They are drawn through a task type too, so the console draws one task
layout and never branches on how old a review is.

The workflow's live version decides first: when its step now names a type, the old review draws with that type, its
params resolved against the old run as the step would have resolved them. Otherwise what the review carries picks one
of the seeded general types (seed/legacy_task_types.json). Only a step decided by approve or reject is drawn this way,
since a type's actions post those two ports; a step with other options keeps its own options."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, cast

from ops_engine.compiler import resolve

from .deps import Runtime
from .engine_lifecycle import definitions
from .task_view import TaskReads, typed_task

# What a review carries (read, reply, write, decision), to the seeded general type that draws it: data, a bridge for
# reviews older than typed steps, which every new review step replaces by naming its own type.
LEGACY_FILE = Path(__file__).resolve().parents[3] / "seed" / "legacy_task_types.json"


@cache
def legacy_types() -> dict[str, str]:
    return cast(dict[str, str], json.loads(LEGACY_FILE.read_text()))


DECIDED_BY = frozenset({"approve", "reject"})
# The live version was not read with the list, so legacy_task reads it (a single review's view).
NOT_READ: Any = object()


async def legacy_task(
    rt: Runtime,
    run: dict[str, Any],
    payload: dict[str, Any],
    view: dict[str, Any],
    *,
    live: Any = NOT_READ,
    reads: TaskReads | None = None,
) -> dict[str, Any] | None:
    """The task screen for an untyped review, or None when it is typed or decided by options other than approve and
    reject. `view` is the review as engine_reviews.view built it, whose words the general types reuse; `live` is the
    version now serving the run's workflow (None for none) when a list read it once for all its runs."""
    if payload.get("taskType"):
        return None
    options = {
        str(cast(dict[str, Any], o).get("name")) if isinstance(o, dict) else str(o)
        for o in cast(list[Any], payload.get("options") or [])
    }
    if options - DECIDED_BY:
        return None
    if live is NOT_READ:
        live = await definitions(rt).current(str(run["workflow_id"]))
    reads = reads or TaskReads(rt, [run], [str(payload.get("step_id") or "")])
    ref, params = await _from_live_version(run, payload, live, reads) or _from_shape(payload, view)
    return await typed_task(rt, {"taskType": ref, "params": params, "step_id": payload.get("step_id")}, run, reads)


async def _from_live_version(
    run: dict[str, Any], payload: dict[str, Any], live: dict[str, Any] | None, reads: TaskReads
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    definition = cast(dict[str, Any], (live or {}).get("definition") or {})
    nodes = cast(list[dict[str, Any]], definition.get("nodes") or [])
    node = next((n for n in nodes if n.get("id") == payload.get("node")), None)
    parameters = cast(dict[str, Any], (node or {}).get("parameters") or {})
    ref = parameters.get("taskType")
    if node is None or node.get("type") != "ops.flow.humanReview" or not isinstance(ref, dict):
        return None
    steps = await reads.steps(run)
    outputs = {str(s["node_id"]): s.get("output") for s in steps if s.get("status") == "ok"}
    params = resolve(parameters.get("params") or {}, {"input": run.get("input"), "nodes": outputs})
    return cast(dict[str, Any], ref), cast(dict[str, Any], params)


def _from_shape(payload: dict[str, Any], view: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    title = str(view.get("question") or view.get("title") or "")
    facts = cast(list[dict[str, Any]], view.get("actionFields") or []) or [
        {"label": e.get("label"), "value": e.get("detail")}
        for e in cast(list[dict[str, Any]], view.get("evidence") or [])
    ]
    decided = {"onApprove": view["consequence"]} if view.get("consequence") else {}
    if isinstance(read := view.get("read"), dict):
        # A read check by its read (engine_reviews.document_read), wherever the workflow put it in the summary; the
        # console draws the read's fields from the review's own `read`.
        found = cast(dict[str, Any], read)
        params = {"title": title, "document": found.get("fileId"), "fields": found.get("schema")}
        return {"id": legacy_types()["read"]}, params | decided
    if isinstance(reply := view.get("reply"), dict):
        sent = cast(dict[str, Any], reply)
        params = {
            "title": title,
            "reply": str(sent.get("body") or ""),
            "facts": [{"label": "To", "value": sent.get("to")}, {"label": "Subject", "value": sent.get("subject")}],
        }
        return {"id": legacy_types()["reply"]}, params | decided
    if isinstance(payload.get("call"), dict):
        return {"id": legacy_types()["write"]}, {"title": title, "call": payload["call"], "facts": facts} | decided
    return {"id": legacy_types()["decision"]}, {"title": title, "facts": facts} | decided
