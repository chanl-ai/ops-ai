"""Reviews opened before their workflow's review step named a task type. They are drawn through a task type too, so
the console draws one task layout and never branches on how old a review is.

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
from ops_engine.store import DefinitionRow
from ops_service_kit.http import Json, JsonList
from ops_service_kit.narrow import json_list, json_object

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
    run: Json,
    payload: Json,
    view: Json,
    *,
    live: Any = NOT_READ,
    reads: TaskReads | None = None,
) -> Json | None:
    """The task screen for an untyped review, or None when it is typed or decided by options other than approve and
    reject. `view` is the review as engine_reviews.view built it, whose words the general types reuse; `live` is the
    version now serving the run's workflow (None for none) when a list read it once for all its runs."""
    if payload.get("taskType"):
        return None
    options = {
        str(o.get("name")) if isinstance(o, dict) else str(o) for o in cast(JsonList, payload.get("options") or [])
    }
    if options - DECIDED_BY:
        return None
    if live is NOT_READ:
        live = await definitions(rt).serving(str(run["workflow_id"]))
    reads = reads or TaskReads(rt, [run], [str(payload.get("step_id") or "")])
    ref, params = await _from_live_version(run, payload, live, reads) or _from_shape(payload, view)
    return await typed_task(rt, {"taskType": ref, "params": params, "step_id": payload.get("step_id")}, run, reads)


async def _from_live_version(
    run: Json, payload: Json, live: DefinitionRow | None, reads: TaskReads
) -> tuple[Json, Json] | None:
    nodes = [json_object(n) for n in json_list(json_object(live.definition if live else None).get("nodes"))]
    node = next((n for n in nodes if n.get("id") == payload.get("node")), None)
    parameters = cast(Json, (node or {}).get("parameters") or {})
    ref = parameters.get("taskType")
    if node is None or node.get("type") != "ops.flow.humanReview" or not isinstance(ref, dict):
        return None
    steps = await reads.steps(run)
    outputs = {s.node_id: s.output for s in steps if s.status == "ok"}
    params = resolve(parameters.get("params") or {}, {"input": run.get("input"), "nodes": outputs})
    return ref, cast(Json, params)


def _from_shape(payload: Json, view: Json) -> tuple[Json, Json]:
    title = str(view.get("question") or view.get("title") or "")
    facts: JsonList = cast(JsonList, view.get("actionFields") or []) or [
        {"label": e.get("label"), "value": e.get("detail")} for e in cast(list[Json], view.get("evidence") or [])
    ]
    decided: Json = {"onApprove": view["consequence"]} if view.get("consequence") else {}
    if isinstance(read := view.get("read"), dict):
        # A read check by its read (engine_reviews.document_read), wherever the workflow put it in the summary; the
        # console draws the read's fields from the review's own `read`.
        found = read
        params: Json = {"title": title, "document": found.get("fileId"), "fields": found.get("schema")}
        return {"id": legacy_types()["read"]}, params | decided
    if isinstance(reply := view.get("reply"), dict):
        sent = reply
        params = {
            "title": title,
            "reply": str(sent.get("body") or ""),
            "facts": [{"label": "To", "value": sent.get("to")}, {"label": "Subject", "value": sent.get("subject")}],
        }
        return {"id": legacy_types()["reply"]}, params | decided
    if isinstance(payload.get("call"), dict):
        params = {"title": title, "call": payload["call"], "facts": facts}
        return {"id": legacy_types()["write"]}, params | decided
    params = {"title": title, "facts": facts}
    return {"id": legacy_types()["decision"]}, params | decided
