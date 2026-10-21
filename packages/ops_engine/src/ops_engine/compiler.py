"""The v2 compiler: a definition becomes a LangGraph StateGraph, and every node runs inside one wrapper.

State is one channel per node instance (`node:<id>`) holding a small envelope `{port, stepId, iteration, out}`, plus
`input`, the run's payload. An out port is a conditional edge reading the envelope's port; a port with no connection
ends the branch (only End has none once a definition passes its checks).

The wrapper (docs/architecture/workflow-runner.md section 4): before a node runs it reads the journal for its run,
node and iteration. A recorded `ok` row (or a `pinned` one, in a test run) returns that output and runs nothing. A
dangling write (its row still `running` after a crash) is reconciled by its key with the tool gateway and never sent
again: found means done, absent means the error port. Otherwise the wrapper writes an attempt row, runs the executor
under a per-attempt timeout and finishes the row, retrying by the type's effects class.

The run id, lease generation and mode come from the LangGraph config's `configurable`, under the same keys the v1 runs
use (`thread_id`, `lease_generation`, `run_id`), so the checkpointer's fence and the gateway's see them.
"""

from __future__ import annotations

import asyncio
import json
import operator
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]
from langgraph.types import interrupt

from . import ai_steps
from .definition import FALLBACK, MAPPING_PREFIX, TEXT_PATH, NodeInstance, WorkflowDefinition
from .journal import Journal, StepRow, StepStatus
from .node_types import CASE_PRIORITIES, DEFAULT_MAX_ITEMS, RETRY_BY_EFFECTS, NodeType, TypeRegistry
from .ports import (
    AgentRequest,
    CaseNotFoundError,
    CaseTypeNotFoundError,
    EnginePorts,
    RunPort,
    RunRefusedError,
    StartedRun,
    ToolResult,
)

CHANNEL = "node:"
INPUT = "input"
DEFAULT_OPTIONS = {"approved": "approve", "rejected": "reject"}


def channel(node_id: str) -> str:
    return f"{CHANNEL}{node_id}"


class WriteInDoubtError(RuntimeError):
    """A write's gateway call is still running, so whether it happened is not known yet. Never a reason to send it
    again; the run is tried again later."""


class StepError(ValueError):
    """A step's refusal that carries a sentence for people (`plain`) beside its technical text (`str()`)."""

    def __init__(self, plain: str, detail: str) -> None:
        super().__init__(detail)
        self.plain = plain


class NodeFailedError(RuntimeError):
    """A node used every attempt its effects class allows and its type has no error port to route the failure to.
    `str()` is the plain message the run shows people; `detail` is the technical text, also kept on the step's row."""

    def __init__(self, plain: str, detail: str) -> None:
        super().__init__(plain)
        self.plain = plain
        self.detail = detail


def technical(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


def plain_failure(step: str, e: BaseException, attempts: int) -> str:
    """What people read when a step fails for good: the step's own sentence when it wrote one, else which step failed.
    The exception's text stays on the step's row, never in this message."""
    if isinstance(e, StepError):
        return e.plain
    tried = f" after {attempts} attempts" if attempts > 1 else ""
    return f"{step} failed{tried}, so the run stopped. The step shows the technical detail."


@dataclass(frozen=True)
class Outcome:
    port: str
    out: Any = None


@dataclass(frozen=True)
class NodeCall:
    run_id: str
    node: NodeInstance
    type: NodeType
    iteration: int
    attempt: int
    key: str
    params: dict[str, Any]
    generation: int | None
    ports: EnginePorts
    run_input: Any
    # The run so far as mappings read it ({input, nodes}), and the definition, for a step that names another node.
    scope: Mapping[str, Any]
    definition: WorkflowDefinition | None = None


Executor = Callable[[NodeCall], Awaitable[Outcome]]


def lookup(path: str, scope: Mapping[str, Any]) -> Any:
    """`$.input.a.b` or `$.nodes.<id>.out.c` read from the run; a missing step reads as None."""
    here: Any = scope
    for part in path[len(MAPPING_PREFIX) :].split("."):
        if isinstance(here, Mapping):
            here = cast(Mapping[str, Any], here).get(part)
        elif isinstance(here, list) and part.isdigit() and int(part) < len(cast(list[Any], here)):
            here = cast(list[Any], here)[int(part)]
        else:
            return None
    return here


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def resolve(value: Any, scope: Mapping[str, Any]) -> Any:
    """A whole-value path reads the value with its type; paths in braces inside a text are filled in as text."""
    if isinstance(value, str) and value.startswith(MAPPING_PREFIX):
        # `$.a ?? $.b`: the first path that reads something, so a step after an optional one reads either.
        for path in value.split(FALLBACK):
            found = lookup(path.strip(), scope)
            if found is not None:
                return found
        return None
    if isinstance(value, str) and "{$." in value:
        return TEXT_PATH.sub(lambda m: _text(lookup(m.group(1), scope)), value)
    if isinstance(value, dict):
        return {k: resolve(v, scope) for k, v in cast(dict[str, Any], value).items()}
    if isinstance(value, list):
        return [resolve(v, scope) for v in cast(list[Any], value)]
    return value


def scope_of(state: Mapping[str, Any]) -> dict[str, Any]:
    nodes = {k[len(CHANNEL) :]: v for k, v in state.items() if k.startswith(CHANNEL) and v is not None}
    return {"input": state.get(INPUT), "nodes": nodes}


# ── executors ──


async def trigger_payload(call: NodeCall) -> Outcome:
    return Outcome("payload", call.run_input)


async def data_set(call: NodeCall) -> Outcome:
    return Outcome("out", dict(call.params.get("values") or {}))


async def data_compute(call: NodeCall) -> Outcome:
    """Calculate: the formulas as the definition holds them, never resolved, so no value from the run can become
    code; the run's data reaches them only as the resolved values, by name."""
    if call.ports.expressions is None:
        raise RuntimeError("no expressions port: this worker cannot evaluate formulas")
    formulas = {str(k): str(v) for k, v in dict(call.node.parameters.get("expressions") or {}).items()}
    out, why = await call.ports.expressions.evaluate(formulas, dict(call.params.get("values") or {}))
    if out is None:
        return Outcome("error", {"error": why, "code": "formula_failed"})
    return Outcome("out", out)


_COMPARE: dict[str, Callable[[Any, Any], bool]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
}


def _holds(condition: Mapping[str, Any]) -> bool:
    left, op, right = condition.get("left"), str(condition.get("op")), condition.get("right")
    if op == "exists":
        return left is not None
    if op == "empty":
        return left in (None, "", [], {})
    if op == "contains":
        return isinstance(left, str | list | dict) and right in cast(Any, left)
    try:
        return bool(_COMPARE[op](left, right))
    except TypeError:
        return False  # a comparison across types (None > 100) is false, not a failed run


async def flow_if(call: NodeCall) -> Outcome:
    conditions = cast(list[Mapping[str, Any]], call.params.get("conditions") or [])
    results = [_holds(c) for c in conditions]
    passed = any(results) if call.params.get("combine") == "any" else all(results)
    return Outcome("true" if passed else "false", {"result": passed})


async def flow_switch(call: NodeCall) -> Outcome:
    """The first way out whose rules hold, in the order the builder listed them; otherwise when none does. Otherwise
    carries every rule it tried, with the value each read, so a run shows why no case matched."""
    cases = cast(list[Mapping[str, Any]], call.params.get("cases") or [])
    for case in cases:
        results = [_holds(c) for c in cast(list[Mapping[str, Any]], case.get("conditions") or [])]
        if results and (any(results) if case.get("combine") == "any" else all(results)):
            return Outcome(str(case["name"]), {"case": str(case["name"])})
    tried = [
        {"case": str(case.get("name")), **{k: c.get(k) for k in ("left", "op", "right")}}
        for case in cases
        for c in cast(list[Mapping[str, Any]], case.get("conditions") or [])
    ]
    return Outcome("otherwise", {"case": "otherwise", "tried": tried})


_NUMBER = re.compile(r"^[-+]?(\d{1,3}(,\d{3})+|\d+)?(\.\d+)?$")


NUMERIC = ("number", "money")


def _fact(value: Any, numeric: bool) -> Any:
    """A value as Combine compares it: an extracted field's `value`; a number as a number; text without case or
    spacing; anything else as its JSON. Text reads as a number (1,200.00 is 1200) only in a `numeric` field: digits in
    a case number or an account id are text, and their leading zeros count."""
    if isinstance(value, Mapping) and "value" in value:
        value = cast(Mapping[str, Any], value)["value"]
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if numeric and text and _NUMBER.match(text) and any(ch.isdigit() for ch in text):
            return float(text.replace(",", ""))
        return _plain_text(text)
    return json.dumps(value, sort_keys=True, default=str)


def _numeric(declared: Any, values: list[Any]) -> bool:
    """A field is a number when the builder typed it number or money, or, untyped, when a read value says it is."""
    if declared:
        return declared in NUMERIC
    return any(isinstance(v, Mapping) and cast(Mapping[str, Any], v).get("type") in NUMERIC for v in values)


def _blank(value: Any) -> bool:
    if isinstance(value, Mapping) and "value" in value:
        value = cast(Mapping[str, Any], value)["value"]
    return value is None or (isinstance(value, str) and not value.strip()) or value in ([], {})


async def data_combine(call: NodeCall) -> Outcome:
    """Each field from its first-ranked source that has it, which source that was, and every field the sources give
    different values for, with each source's value. An empty value is no value, so it never disagrees."""
    sources: list[tuple[str, Mapping[str, Any]]] = []
    for raw in cast(list[Mapping[str, Any]], call.params.get("sources") or []):
        found = raw.get("values")
        sources.append((str(raw["name"]), cast(Mapping[str, Any], found) if isinstance(found, Mapping) else {}))
    by_name = dict(sources)
    order = [name for name, _ in sources]
    listed = cast(list[Mapping[str, Any]], call.params.get("fields") or [])
    ranked: dict[str, list[str]] = {}
    for f in listed:
        ranks = [str(n) for n in cast(list[Any], f.get("from") or []) if str(n) in by_name]
        if ranks:
            ranked[str(f["field"])] = ranks
    typed = {str(f["field"]): f.get("type") for f in listed}
    names = list(dict.fromkeys([*ranked, *(field for _, values in sources for field in values)]))
    values: dict[str, Any] = {}
    picked: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []
    for field in names:
        present = [
            (n, by_name[n].get(field)) for n in (ranked.get(field) or order) if not _blank(by_name[n].get(field))
        ]
        if not present:
            continue
        values[field], picked[field] = present[0][1], present[0][0]
        numeric = _numeric(typed.get(field), [v for _, v in present])
        if len({json.dumps(_fact(v, numeric), default=str) for _, v in present}) > 1:
            conflicts.append({"field": field, "values": [{"source": n, "value": v} for n, v in present]})
    out = {"values": values, "sources": picked, "conflicts": conflicts, "hasConflicts": bool(conflicts)}
    return Outcome("out", out)


def _plain_text(value: Any) -> str:
    return "" if value is None else " ".join(str(value).split()).casefold()


def _field(row: Any, name: str) -> Any:
    here: Any = row
    for part in name.split("."):
        here = cast(Mapping[str, Any], here).get(part) if isinstance(here, Mapping) else None
    return here


def _rule_holds(rule: Mapping[str, Any], item: Any, candidate: Any) -> bool:
    left = _plain_text(_field(item, str(rule["left"])))
    right = _plain_text(_field(candidate, str(rule["right"])))
    if not left or not right:
        return False  # an empty value never matches: a blank address is not "in" every address
    if rule.get("op") == "overlaps":
        return min(len(left), len(right)) >= int(rule.get("minLength") or 1) and (left in right or right in left)
    return left == right


async def data_match(call: NodeCall) -> Outcome:
    raw = call.params.get("candidates")
    listed: list[Any] = cast(list[Any], raw) if isinstance(raw, list) else [raw] if isinstance(raw, Mapping) else []
    rows: list[Mapping[str, Any]] = [cast(Mapping[str, Any], r) for r in listed if isinstance(r, Mapping)]
    item = call.params.get("item")
    every = cast(list[Mapping[str, Any]], call.params.get("all") or [])
    some = cast(list[Mapping[str, Any]], call.params.get("any") or [])
    matches = [
        r
        for r in rows
        if all(_rule_holds(x, item, r) for x in every) and (not some or any(_rule_holds(x, item, r) for x in some))
    ]
    return Outcome(
        "matched" if matches else "none",
        {"match": matches[0] if matches else None, "matches": matches, "candidates": rows},
    )


def next_iteration(scope: Mapping[str, Any], node_id: str) -> int:
    env = cast(Mapping[str, Any], cast(Mapping[str, Any], scope.get("nodes") or {}).get(node_id) or {})
    return int(env.get("iteration") or 0) + 1


def write_call(call: NodeCall, node_id: str) -> dict[str, Any]:
    """The call tool node `node_id` will make, as a review approves it: its operation, its input resolved against the
    run so far, and the key its first attempt sends (a write gets one attempt). The approval token a decision mints is
    bound to exactly this thread, step, operation and input."""
    target = call.definition.node(node_id) if call.definition else None
    if target is None:
        raise ValueError(f"{call.node.id} approves {node_id}, which is not a node of this workflow")
    params = cast(dict[str, Any], resolve(target.parameters, call.scope))
    arguments = dict(cast(dict[str, Any], params.get("input") or {}))
    if missing := sorted(k for k, v in arguments.items() if v is None):
        # Approving a call with a value read as nothing would bind the token to it; refuse instead.
        plain = (
            f"{call.node.name or call.node.id} could not open: {target.name or node_id} has no "
            f"{', '.join(missing)} to use from this run."
        )
        raise StepError(plain, f"{node_id}'s input {', '.join(missing)} is empty when {call.node.id} opens")
    step = f"{call.run_id}:{node_id}:{next_iteration(call.scope, node_id)}:1"
    return {"tool": str(params.get("operation")), "input": arguments, "step": step}


# The gateway's codes for a system that did not answer in time: no connection in time, or no answer once connected.
TIMEOUT_CODES = frozenset({"UPSTREAM_TIMEOUT", "CONNECT_TIMEOUT"})


def _error_code(output: Any) -> str | None:
    """The gateway's failure code in a tool's output (`{"error": {"code": ...}}`), or None."""
    if not isinstance(output, dict):
        return None
    error: Any = cast(dict[str, Any], output).get("error")
    return str(cast(dict[str, Any], error).get("code")) if isinstance(error, dict) else None


async def gateway_call(call: NodeCall) -> Outcome:
    token = call.params.get("approvalToken")
    arguments = dict(call.params.get("input") or {})
    if reviewer := call.params.get("approvedBy"):
        # A reviewed write: the call the decision approved, with the token minted for it. With no approval (a
        # rejection, or no decision) it is sent without a token and the gateway refuses it.
        env = cast(Mapping[str, Any], cast(Mapping[str, Any], call.scope.get("nodes") or {}).get(str(reviewer)) or {})
        out = cast(Mapping[str, Any], env.get("out") or {})
        approved = cast(Mapping[str, Any], out.get("call") or {})
        if approved.get("tool") == call.params.get("operation") and approved.get("step") == call.key:
            arguments = dict(cast(Mapping[str, Any], approved.get("input") or {}))
            # Minted here from the recorded approvals and sent at once; never written to state or the journal.
            approval = cast(Mapping[str, Any] | None, out.get("approval"))
            token = await call.ports.tools.mint(call.run_id, dict(approved), dict(approval)) if approval else None
        else:
            token = None
    result: ToolResult = await call.ports.tools.call(
        str(call.params["operation"]),
        arguments,
        call.key,
        call.generation,
        str(token) if token else None,
    )
    if result.ok:
        return Outcome("ok", result.output)
    if result.refused:
        return Outcome("refused", {"reason": result.reason})
    if call.params.get("onTimeout") == "port" and _error_code(result.output) in TIMEOUT_CODES:
        # The system did not answer in time (c-332): the step's own port, for a workflow that handles it apart.
        return Outcome("timeout", {"error": result.output, "reason": result.reason})
    return Outcome("error", {"error": result.output, "reason": result.reason})


async def review_open(call: NodeCall) -> Outcome:
    options = call.type.output_ports(call.params)
    step_id = f"{call.run_id}:{call.node.id}:{call.iteration}"
    payload: dict[str, Any] = {
        "kind": "review",
        "node": call.node.id,
        "review_id": step_id,
        "step_id": step_id,
        "iteration": call.iteration,
        "title": call.params.get("title") or call.node.name or call.node.id,
        "draft": call.params.get("summary"),
        # The deadline's facts; the host applies the workspace's default when slaHours is unset and expires the step.
        "openedAt": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "onTimeout": call.params.get("onTimeout") or "wait",
    }
    if call.params.get("slaHours") is not None:
        payload["slaHours"] = float(call.params["slaHours"])
    if call.params.get("remindEveryHours"):
        payload["remindEveryHours"] = float(call.params["remindEveryHours"])
    for key in ("notDecidedBy", "requestedBy"):
        if key in call.node.parameters:
            given = call.params.get(key)
            named = cast(list[Any], given) if isinstance(given, list) else [given]
            payload[key] = sorted({str(x).strip().lower() for x in named if x})
    editable = "editable" in call.node.parameters
    if editable:
        payload["editable"] = {"path": call.node.parameters["editable"], "value": call.params.get("editable")}
    if approves := call.params.get("approves"):
        payload["call"] = write_call(call, str(approves))
    if ref := call.params.get("taskType"):
        if not isinstance(ref, dict) or not cast(dict[str, Any], ref).get("id"):
            raise ValueError(f"{call.node.id}: taskType read {ref!r}, not {{id, version}}")
        typed = cast(dict[str, Any], ref)
        version = cast(int | None, typed.get("version"))
        if call.ports.task_types is not None:
            version = await call.ports.task_types.pin(str(typed["id"]), version)
        payload["taskType"] = {"id": str(typed["id"]), "version": version}
        payload["params"] = dict(cast(dict[str, Any], call.params.get("params") or {}))
    if "options" in call.params:
        listed: list[dict[str, Any]] = []
        for raw in cast(list[Any], call.params["options"]):
            o = dict(cast(dict[str, Any], raw)) if isinstance(raw, dict) else {"name": str(raw)}
            declared: dict[str, Any] = {"name": o["name"], "label": o.get("label") or str(o["name"]).capitalize()}
            if isinstance(o.get("call"), dict) and cast(dict[str, Any], o["call"]).get("node"):
                declared["call"] = write_call(call, str(cast(dict[str, Any], o["call"])["node"]))
                declared["inputs"] = list(cast(list[Any], o.get("inputs") or []))
            listed.append(declared)
        payload["options"] = listed
    payload["review_id"] = await call.ports.reviews.open(call.run_id, call.node.id, call.iteration, payload)
    decision: Any = interrupt(payload)
    chosen = dict(cast(dict[str, Any], decision)) if isinstance(decision, dict) else {"decision": decision}
    port = str(chosen.get("option") or DEFAULT_OPTIONS.get(str(chosen.get("decision")), chosen.get("decision")))
    if port not in options:
        raise ValueError(f"{call.node.id} was decided {port!r}; its options are {', '.join(options)}")
    out = {
        "decision": port,
        "reason": chosen.get("reason"),
        "by": chosen.get("by"),
        # The recorded approvals this decision rests on (step, input hash, approvers); the token is minted from them
        # only at the call.
        "approval": chosen.get("approval"),
        # The write this decision approved, as the reviewer's inputs completed it; the tool node sends exactly this.
        "call": chosen.get("call") or (payload.get("call") if port == "approve" else None),
    }
    if editable:
        # engine_reviews checked a correction's shape against the value before resuming.
        out["edited"] = chosen["edited"] if "edited" in chosen else call.params.get("editable")
    if isinstance(chosen.get("inputs"), dict):
        # A typed action's own inputs, checked against the type (c-329): a Reject's assignee routes the next step.
        out["inputs"] = chosen["inputs"]
    return Outcome(port, out)


async def kernel_turn(call: NodeCall) -> Outcome:
    if call.ports.agents is None:
        raise RuntimeError("no agent port: this worker runs no agent turns (no model configured)")
    prompt = str(call.params.get("prompt") or "").strip()
    data = json.dumps(call.params.get("input") or {}, ensure_ascii=False, sort_keys=True)
    request = AgentRequest(
        agent_id=str(call.params["agent"]),
        message=f"{prompt}\n\nInput:\n{data}" if prompt else data,
        # Not the attempt: a retried turn repeats its tool keys, so the gateway answers a write once.
        turn_id=f"{call.run_id}:{call.node.id}:{call.iteration}",
        output_schema=cast(dict[str, Any] | None, call.params.get("outputSchema")),
        model_alias=cast(str | None, call.params.get("model")) or None,
        max_tool_calls=cast(int | None, call.params.get("maxToolCalls")),
    )
    result = await call.ports.agents.turn(request)
    if result.ok and request.output_schema is not None and result.output is None:
        # The step asked for structured output and got none: its error port, whatever the port called the turn.
        why = result.text or "The agent gave no answer matching the step's output schema."
        return Outcome("error", {"error": why, "code": "no_output"})
    if result.ok:
        return Outcome("ok", result.output if request.output_schema is not None else {"text": result.text})
    return Outcome("error", {"error": result.error, "code": result.code})


async def ai_prompt(call: NodeCall) -> Outcome:
    """Classify, Summarise, Extract from text and Draft (c-298): one model call with the step's own instructions and
    the answer schema its job builds from the settings (ai_steps.JOBS), no saved agent and no tools. An answer outside
    the schema takes the error port at once; a model that cannot be reached is raised, so the wrapper retries it."""
    if call.ports.prompts is None:
        raise RuntimeError("no prompt port: this worker runs no AI steps (no model configured)")
    types = call.ports.document_types

    async def lookup(type_id: str, version: int | None) -> list[dict[str, Any]]:
        assert types is not None
        return await types.fields(call.run_id, type_id, version)

    params = await ai_steps.resolve_fields(call.params, lookup if types is not None else None)
    port, out = await ai_steps.run(
        call.type.id,
        params,
        call.ports.prompts,
        turn_id=f"{call.run_id}:{call.node.id}:{call.iteration}",
        run_id=call.run_id,
    )
    return Outcome(port, out)


async def ai_extract(call: NodeCall) -> Outcome:
    """Extract from file (c-157, c-235, c-256): documents-service's extraction API reads the file and scores every
    field; the step maps its answer onto the ports. A failure documents-service may get past on a retry (the floor or
    the model out of reach) is raised, so the wrapper retries it under the same key."""
    if call.ports.documents is None:
        raise RuntimeError("no documents port: this worker cannot run Extract from file")
    file_id = str(call.params.get("file") or "")
    below = call.params.get("reviewBelow")
    request: dict[str, Any] = {
        "fields": list(cast(list[Any], call.params.get("fields") or [])),
        "many": bool(call.params.get("many")),
        "ocr": bool(call.params.get("ocr")),
        "reviewBelow": float(below) if isinstance(below, int | float) else None,
    }
    # A documentType whose id resolved to nothing (a read request that named no type, c-335) is no type at all.
    doc_type = cast(dict[str, Any] | None, call.params.get("documentType"))
    if doc_type is not None and not doc_type.get("id"):
        doc_type = None
    if call.params.get("detect") and not doc_type and not call.params.get("fields"):
        # documents-service classifies the file over the team's types and reads it with the kind found (c-249).
        request = {"detect": True, "ocr": request["ocr"], "reviewBelow": request["reviewBelow"]}
    elif doc_type:
        # The type's version holds the fields and `many`; the version was pinned when the workflow was saved.
        request = {
            "documentTypeId": doc_type["id"],
            "version": doc_type.get("version"),
            "ocr": request["ocr"],
            "reviewBelow": request["reviewBelow"],
        }
    key = f"{call.run_id}:{call.node.id}:{call.iteration}"
    answer = await call.ports.documents.extract(call.run_id, file_id, request, key=key)
    status = answer.get("status")
    if status == "failed":
        error = cast(dict[str, Any], answer.get("error") or {})
        if error.get("code") == "schema_error":
            return Outcome(
                "error", {"error": error.get("message"), "code": "schema_error", "details": error.get("details")}
            )
        raise RuntimeError(f"the extraction failed ({error.get('code')}): {error.get('message')}")
    # The extraction's id stays on the output: the run page links the read to it, and its model call is logged under it.
    out = {k: v for k, v in answer.items() if k not in ("id", "status", "outcome", "corrections")} | {
        "extractionId": answer.get("id")
    }
    if status == "unreadable":
        return Outcome("unreadable", out)
    if status == "done" and answer.get("outcome") == "unknown":
        # No kind of the team's fits, or the model is unsure: review, with no fields, so a person decides what the
        # file is; `classification` on the output says why (c-249).
        return Outcome("review", out)
    if status != "done" or answer.get("outcome") not in ("ok", "review"):
        # A state this step does not know is raised, never turned into a port it does not have.
        raise RuntimeError(f"documents-service answered status {status!r} with outcome {answer.get('outcome')!r}")
    return Outcome(str(answer["outcome"]), out)


def read_on_file(read: dict[str, Any], *, checked: bool, type_name: Any) -> dict[str, Any] | None:
    """What a file records of a read (c-250): its type and version, template or model, the fields waiting for a person
    and the extraction; None for a read naming no document type or extraction, never data made up for the file. A
    Detect read that found none of the team's types is recorded with no type, as not recognised (c-335)."""
    doc_type = cast(dict[str, Any], read.get("documentType") or {})
    classification = cast(dict[str, Any], read.get("classification") or {})
    unrecognised = not doc_type.get("id") and bool(classification)
    if (not doc_type.get("id") and not unrecognised) or not read.get("extractionId"):
        return None
    data: dict[str, Any] = {
        "typeId": None if unrecognised else str(doc_type["id"]),
        "version": None if unrecognised else int(doc_type.get("version") or 1),
        "path": str(read.get("path") or "model"),
        # After a person checked the fields none wait; otherwise those under the threshold (records, for several).
        "fieldsToCheck": 0 if checked else len(cast(list[Any], read.get("needsReview") or [])),
        "extractionId": str(read["extractionId"]),
        "readAt": datetime.now(UTC).isoformat(),
    }
    # The type a person chose names itself; otherwise the read's type, or the kind a Detect read found.
    if not unrecognised and (name := type_name or doc_type.get("name") or classification.get("name")):
        data["typeName"] = str(name)
    if template := read.get("templateId"):
        # A read from a layout template (c-253) names it, so the files list can say which form a file was read as.
        data["templateId"] = str(template)
    return data


async def files_set_data(call: NodeCall) -> Outcome:
    """Save data on file (c-250): what an Extract from file step read, recorded on the file through files-service as the
    run's team, so the files list shows and filters it. A Detect read that found none of the team's types is saved with
    no type, as not recognised (c-335); any other read naming no document type or extraction is an error, never data
    made up for the file."""
    if call.ports.file_data is None:
        raise RuntimeError("no file data port: this worker cannot run Save data on file")
    read = cast(dict[str, Any], call.params.get("read") or {})
    data = read_on_file(read, checked=bool(call.params.get("checked")), type_name=call.params.get("typeName"))
    if data is None:
        return Outcome("error", {"error": "The read names no document type or extraction.", "code": "no_read"})
    saved = await call.ports.file_data.set_data(call.run_id, str(call.params.get("file") or ""), data)
    return Outcome("ok", {"data": saved.get("data", data)})


async def documents_purge(call: NodeCall) -> Outcome:
    """Purge what was read from a file (c-250): the extractions and samples documents-service holds for a deleted file,
    as the run's team. Repeating it removes nothing more."""
    if call.ports.documents is None:
        raise RuntimeError("no documents port: this worker cannot purge what was read from a file")
    return Outcome("ok", await call.ports.documents.purge(call.run_id, str(call.params.get("file") or "")))


async def workflow_start(call: NodeCall) -> Outcome:
    """Start workflow: one child, or one per item of `forEach`, each keyed by this run, step, iteration and item so a
    retried or re-run step finds its children instead of starting more. A refusal stops at the item it refused, with
    the children already started listed, and they stay started."""
    if call.ports.runs is None:
        raise RuntimeError("no run port: this worker cannot start workflows")
    workflow = str(call.params["workflow"])
    raw_input = cast(dict[str, Any], call.node.parameters.get("input") or {})
    looping = call.node.parameters.get("forEach") not in (None, "")
    items: list[Any] = [None]
    if looping:
        listed = call.params.get("forEach")
        if not isinstance(listed, list):
            what = type(listed).__name__ if listed is not None else "nothing"
            return Outcome("error", {"error": f"For each read {what}, not a list.", "code": "not_a_list"})
        limit = int(call.params.get("maxItems") or DEFAULT_MAX_ITEMS)
        if len(cast(list[Any], listed)) > limit:
            message = f"For each read {len(cast(list[Any], listed))} items; this step starts at most {limit}."
            return Outcome("error", {"error": message, "code": "too_many_items"})
        items = cast(list[Any], listed)
    prefix = f"{call.run_id}:{call.node.id}:{call.iteration}:"

    async def start(index: int, item: Any) -> StartedRun:
        scope = {**call.scope, "item": item, "index": index} if looping else call.scope
        child_input = cast(dict[str, Any], resolve(raw_input, scope))
        return await cast(RunPort, call.ports.runs).start(call.run_id, workflow, child_input, f"{prefix}{index}")

    if not call.params.get("wait"):
        started: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            try:
                child = await start(index, item)
            except RunRefusedError as e:
                return Outcome("error", {"error": str(e), "code": e.code, "runs": started})
            started.append({"index": index, "runId": child.run_id, "created": child.created})
        return Outcome("started", {"workflowId": workflow, "count": len(started), "runs": started})
    return await _wait_for_children(call, workflow, items, start, prefix)


ENDED = ("succeeded", "failed", "cancelled")
# A child's output kept in the parent's step output; a larger one is named by its run id instead.
CHILD_OUTPUT_MAX_BYTES = 64 * 1024


def _collected(workflow: str, children: list[dict[str, Any]], total: int) -> dict[str, Any]:
    """The children that ended, in item order, with a count by outcome; an output over the size cap is left out."""
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for c in children:
        if c["status"] not in ENDED:
            continue
        output = c.get("output")
        big = len(json.dumps(output, default=str)) > CHILD_OUTPUT_MAX_BYTES
        outcome = str(c.get("outcome") or c["status"])
        rows.append({"index": c["index"], "runId": c["runId"], "outcome": outcome, "output": None if big else output})
        counts[outcome] = counts.get(outcome, 0) + 1
    return {"workflowId": workflow, "count": total, "children": rows, "counts": counts}


async def _wait_for_children(
    call: NodeCall,
    workflow: str,
    items: list[Any],
    start: Callable[[int, Any], Awaitable[StartedRun]],
    prefix: str,
) -> Outcome:
    """Run workflow with Wait for them (c-263): start up to `batchSize` children, pause, and on each resume (a child
    ended, or the step's timeout fell due) read them all in one call, start more, and go on by `done` once every child
    has ended, or by `timeout` with the rest named. A refused start still takes the error port."""
    runs = cast(RunPort, call.ports.runs)
    batch = int(call.params.get("batchSize") or len(items) or 1)
    hours = call.params.get("timeoutHours")
    resumed: Any = None

    async def with_outputs() -> list[dict[str, Any]]:
        # States are read on every wake, outputs once, when the step goes on.
        return await runs.children(call.run_id, prefix, outputs=True)

    while True:
        children = await runs.children(call.run_id, prefix)
        begun = {int(c["index"]) for c in children}
        unfinished = sum(1 for c in children if c["status"] not in ENDED)
        for index, item in enumerate(items):
            if unfinished >= batch:
                break
            if index in begun:
                continue
            try:
                await start(index, item)
            except RunRefusedError as e:
                so_far = _collected(workflow, await with_outputs(), len(items))["children"]
                return Outcome("error", {"error": str(e), "code": e.code, "runs": so_far})
            begun.add(index)
            unfinished += 1
        if len(begun) == len(items) and unfinished == 0:
            return Outcome("done", _collected(workflow, await with_outputs(), len(items)))
        if isinstance(resumed, dict) and cast(dict[str, Any], resumed).get("timeout"):
            out = _collected(workflow, await with_outputs(), len(items))
            ended = {c["index"] for c in out["children"]}
            waiting = [c["runId"] for c in children if c["index"] not in ended]
            return Outcome("timeout", out | {"waiting": waiting, "notStarted": len(items) - len(begun)})
        resumed = interrupt(
            {
                "kind": "children",
                "node": call.node.id,
                "iteration": call.iteration,
                "workflowId": workflow,
                "total": len(items),
                "timeoutHours": hours,
                "wakeAfterSeconds": float(hours) * 3600 if hours else None,
            }
        )


CASE_FIELDS = ("subject", "priority", "customerId", "customerName", "assignee", "caseType", "fields")


async def case_open(call: NodeCall) -> Outcome:
    """Open case: keyed by this run, step and iteration, so a retried or re-run step finds its case."""
    if call.ports.cases is None:
        raise RuntimeError("no case port: this worker cannot open cases")
    fields = {k: call.params[k] for k in CASE_FIELDS if call.params.get(k) not in (None, "")}
    if not str(fields.get("subject") or "").strip():
        return Outcome("error", {"error": "Open case needs a subject.", "code": "subject_required"})
    if fields.get("priority", "normal") not in CASE_PRIORITIES:
        why = f"Open case read priority {fields.get('priority')!r}; it must be one of {', '.join(CASE_PRIORITIES)}."
        return Outcome("error", {"error": why, "code": "priority_invalid"})
    try:
        opened = await call.ports.cases.open(call.run_id, fields, f"{call.run_id}:{call.node.id}:{call.iteration}")
    except CaseTypeNotFoundError:
        why = f"Open case names case type {fields.get('caseType')!r}, which has no published version."
        return Outcome("error", {"error": why, "code": "case_type_unknown"})
    return Outcome("opened", {"caseId": opened.case_id, "created": opened.created})


async def case_add(call: NodeCall) -> Outcome:
    """Add to case: the run joins a case of its own team; any other case is the error port."""
    if call.ports.cases is None:
        raise RuntimeError("no case port: this worker cannot add to cases")
    case_id = str(call.params.get("caseId") or "")
    if not case_id:
        return Outcome("error", {"error": "Add to case read no case id.", "code": "case_required"})
    note = call.params.get("note")
    fields = call.params.get("fields")
    try:
        await call.ports.cases.add(
            call.run_id, case_id, str(note) if note else None, cast(dict[str, Any], fields) if fields else None
        )
    except CaseNotFoundError:
        return Outcome("error", {"error": f"No case {case_id} in this run's team.", "code": "case_not_found"})
    return Outcome("added", {"caseId": case_id})


async def flow_end(call: NodeCall) -> Outcome:
    out = {"outcome": str(call.params.get("outcome") or "done"), "output": call.params.get("output")}
    if call.params.get("result") == "failed":
        out |= {"result": "failed", "name": call.node.name or call.node.id}
    return Outcome("", out)


async def flow_join(call: NodeCall) -> Outcome:
    """Join (c-278): each step connected to it, by id, with its output when it left by the connected port, or None
    when it took another port or never ran. The compiler adds a Join deferred, so this runs once, after every branch
    that can still arrive."""
    nodes = cast(dict[str, Any], call.scope.get("nodes") or {})
    branches: dict[str, Any] = {}
    for c in call.definition.connections if call.definition else []:
        if c.target.node != call.node.id:
            continue
        env = cast(dict[str, Any] | None, nodes.get(c.source.node))
        took = env is not None and env.get("port") == c.source.port
        if took or c.source.node not in branches:
            branches[c.source.node] = cast(dict[str, Any], env).get("out") if took else None
    return Outcome("out", branches)


def _instant(value: Any) -> datetime | None:
    """An ISO date or date and time as an aware datetime: a date alone is midnight, no offset is UTC. None when the
    value is not one."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        at = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


async def flow_wait(call: NodeCall) -> Outcome:
    """Wait (c-277): pauses until its time has passed, then goes on by `out`. The pause is an interrupt the worker
    wakes with delayed work keyed by step and iteration, so no worker is held and a restart loses nothing. On resume the
    step runs again: a date now past goes on without pausing, a duration takes the resume its first pause asked for."""
    if call.params.get("mode") == "until":
        raw = call.params.get("until")
        due = _instant(raw)
        if due is None:
            return Outcome("error", {"error": f"{raw!r} is not a date", "code": "not_a_date", "value": raw})
        out: dict[str, Any] = {"until": due.isoformat().replace("+00:00", "Z")}
        seconds = (due - datetime.now(UTC)).total_seconds()
    else:
        seconds = float(call.params.get("seconds") or 0)
        out = {"seconds": seconds}
    if seconds > 0:
        interrupt(
            {"kind": "wait", "node": call.node.id, "iteration": call.iteration, "wakeAfterSeconds": seconds} | out
        )
    return Outcome("out", out)


EXECUTORS: dict[str, Executor] = {
    "trigger.payload": trigger_payload,
    "data.set": data_set,
    "data.compute": data_compute,
    "flow.if": flow_if,
    "flow.switch": flow_switch,
    "flow.join": flow_join,
    "flow.wait": flow_wait,
    "data.combine": data_combine,
    "data.match": data_match,
    "gateway.call": gateway_call,
    "review.open": review_open,
    "kernel.turn": kernel_turn,
    "ai.extract": ai_extract,
    "ai.prompt": ai_prompt,
    "files.setData": files_set_data,
    "documents.purge": documents_purge,
    "workflow.start": workflow_start,
    "case.open": case_open,
    "case.add": case_add,
    "flow.end": flow_end,
}


# ── the wrapper ──


def _envelope(row: StepRow) -> dict[str, Any]:
    return {
        "port": row.port or "",
        "stepId": f"{row.run_id}:{row.node_id}:{row.iteration}",
        "iteration": row.iteration,
        "out": row.output,
    }


@dataclass
class Wrapper:
    node: NodeInstance
    type: NodeType
    ports: EnginePorts
    journal: Journal
    definition: WorkflowDefinition | None = None

    async def effects(self, params: Mapping[str, Any]) -> str:
        if self.type.executor == "gateway.call":
            access = await self.ports.tools.access(str(params.get("operation")))
            return "read" if access == "read" else "write"  # unknown counts as a write: one attempt, reconciled
        return self.type.effects

    async def __call__(self, state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        cfg: dict[str, Any] = dict(config.get("configurable") or {})
        run_id = str(cfg["run_id"])
        generation = cast(int | None, cfg.get("lease_generation"))
        test_mode = cfg.get("engine_mode") == "test"
        nid = self.node.id
        prev = cast(dict[str, Any] | None, state.get(channel(nid)))
        iteration = int(prev["iteration"]) + 1 if prev else 1
        # Rows read back are written by this worker from here on, under its own generation.
        rows = [replace(r, generation=generation) for r in await self.journal.steps(run_id, nid, iteration)]
        if not self.ports.faults.ignore_recorded:
            done = next((r for r in rows if recorded(r) or (r.status == "pinned" and test_mode)), None)
            if done is not None:
                return {channel(nid): _envelope(done)}
        params = cast(dict[str, Any], resolve(self.node.parameters, scope_of(state)))
        last = rows[-1] if rows else None

        def row(attempt: int, effects: str, status: Any = "running") -> StepRow:
            key = f"{run_id}:{nid}:{iteration}:{attempt}"
            return StepRow(
                run_id,
                nid,
                iteration,
                attempt,
                status,
                effects,
                key,
                input=redacted(params),
                generation=generation,
                node_type=self.type.id,
            )

        def call(r: StepRow) -> NodeCall:
            return NodeCall(
                run_id,
                self.node,
                self.type,
                iteration,
                r.attempt,
                r.key,
                params,
                generation,
                self.ports,
                state.get(INPUT),
                scope_of(state),
                self.definition,
            )

        executor = EXECUTORS[self.type.executor]
        if self.type.effects == "human":
            # A review raises an interrupt and is re-run on resume: its waiting row is the same attempt.
            r = (
                last
                if last is not None and last.status == "waiting"
                else row((last.attempt if last else 0) + 1, "human")
            )
            if r is not last:
                await self.journal.begin(replace(r, status="waiting"))
            try:
                outcome = await executor(call(r))
            except GraphInterrupt:
                raise
            except Exception as e:
                # A review that cannot open (its approved write reads nothing) is a failed step, kept on its row.
                detail = technical(e)
                await self.journal.finish(r, status="error", port=None, output=None, error=detail)
                await self.ports.hooks.after_step(run_id, nid, "error")
                raise NodeFailedError(plain_failure(self.node.name or nid, e, 1), detail) from e
            return await self.record(r, outcome)

        if last is not None and last.status == "waiting":
            # A step that paused (Run workflow waiting for its children, c-263) resumes in the same attempt: its
            # writes are keyed by step and item, so running it again starts nothing twice.
            try:
                return await self.record(last, await executor(call(last)))
            except GraphInterrupt:
                raise
        effects = await self.effects(params)
        # The dangling attempt's own effects decide, not the operation's class now: a write reclassified as a read
        # after a crash is still a write that may have happened.
        # An idempotent write is keyed by its step, so it is retried like a read instead.
        reconciled = effects == "write" and not self.type.idempotent
        if (
            last is not None
            and last.status in ("running", "error")
            and last.effects == "write"
            and not self.type.idempotent
        ):
            # A write that may have reached the gateway (its process died mid-call, or the call raised) is never sent
            # again: its own key decides what happened.
            return await self.reconcile(last)
        if last is not None and last.status == "running":
            await self.journal.finish(last, status="abandoned", port=None, output=None, error="its process died")
        policy = self.type.retry_policy() if effects == self.type.effects else RETRY_BY_EFFECTS[cast(Any, effects)]
        attempt = (last.attempt if last else 0) + 1
        first = attempt
        timeout = float(self.node.parameters.get("timeoutSeconds") or self.type.timeout_seconds)
        while True:
            r = row(attempt, effects)
            await self.journal.begin(r)
            try:
                outcome = await asyncio.wait_for(executor(call(r)), timeout)
            except GraphInterrupt:
                # Paused (c-263), not dead: the attempt is marked waiting so a resume continues it.
                await self.journal.finish(r, status="waiting", port=None, output=None, error=None)
                raise
            except Exception as e:
                message = technical(e)
                if reconciled:
                    # A timeout or a 5xx says nothing about whether the write happened; the gateway's record does.
                    return await self.reconcile(r, cause=message)
                if attempt - first + 1 < policy.attempts:
                    await self.journal.finish(r, status="error", port=None, output=None, error=message)
                    await self.ports.hooks.after_step(run_id, nid, "error")
                    attempt += 1
                    await asyncio.sleep(policy.wait(attempt - first + 1))
                    continue
                if "error" in self.type.output_ports(self.node.parameters):
                    return await self.record(r, Outcome("error", {"error": message}), error=message)
                await self.journal.finish(r, status="error", port=None, output=None, error=message)
                await self.ports.hooks.after_step(run_id, nid, "error")
                tried = attempt - first + 1
                detail = f"{nid} failed after {tried} attempts: {message}"
                raise NodeFailedError(plain_failure(self.node.name or nid, e, tried), detail) from e
            return await self.record(r, outcome)

    async def record(self, r: StepRow, outcome: Outcome, *, error: str | None = None) -> dict[str, Any]:
        """Finishes the attempt with the port it leaves by. The error port is recorded as an error, and like any
        recorded port it is returned on a re-run instead of running the node again."""
        status: StepStatus = "error" if outcome.port == "error" else "ok"
        await self.journal.finish(r, status=status, port=outcome.port, output=outcome.out, error=error)
        await self.ports.hooks.after_step(r.run_id, r.node_id, status)
        return {channel(r.node_id): _envelope(replace(r, port=outcome.port, output=outcome.out))}

    async def reconcile(self, dangling: StepRow, *, cause: str | None = None) -> dict[str, Any]:
        """A write whose outcome is unknown: the gateway's record under the attempt's own key decides. Found done
        means the write happened; refused or failed is that port; absent means it never arrived, and the run takes the
        error port rather than risk a second send. A call the gateway is still running is not yet known: the pass
        stops with WriteInDoubtError and the worker tries the run again later, the row left as it is."""
        operation = str(cast(dict[str, Any], dangling.input or {}).get("operation") or "")
        found = await self.ports.tools.find(dangling.key, operation)
        if found is not None and found.pending:
            raise WriteInDoubtError(f"{dangling.key} is still running at the gateway")
        if found is not None and found.ok:
            outcome = Outcome("ok", found.output)
        elif found is not None and found.refused:
            outcome = Outcome("refused", {"reason": found.reason})
        else:
            reason = found.reason if found is not None else "the gateway has no record of the write"
            outcome = Outcome("error", {"error": found.output if found else None, "reason": reason, "cause": cause})
        return await self.record(dangling, outcome, error=cause if outcome.port == "error" else None)


SECRET_KEYS = frozenset({"approvalToken", "approval_token"})


def redacted(value: Any) -> Any:
    """`value` with every approval token replaced: what the journal and a run's detail may hold."""
    if isinstance(value, dict):
        items = cast(dict[str, Any], value).items()
        return {k: ("[redacted]" if k in SECRET_KEYS and v else redacted(v)) for k, v in items}
    if isinstance(value, list):
        return [redacted(v) for v in cast(list[Any], value)]
    return value


def recorded(r: StepRow) -> bool:
    """A finished attempt that left by a port: its output is the step's, on every re-run."""
    return r.port is not None and r.status in ("ok", "error")


# ── the graph ──


def compile_definition(
    d: WorkflowDefinition,
    registry: TypeRegistry,
    *,
    ports: EnginePorts,
    journal: Journal,
    checkpointer: Any,
) -> Any:
    """The definition as a compiled LangGraph graph on `checkpointer`. The definition must have passed `validate`."""
    fields: dict[str, Any] = {INPUT: Any, **{channel(n.id): dict[str, Any] | None for n in d.nodes}}
    state = TypedDict("WorkflowState", fields, total=False)  # type: ignore[misc]  # names are runtime data
    g: Any = StateGraph(cast(Any, state))
    trigger = ""
    for n in d.nodes:
        t = registry.get(n.type, n.type_version)
        if t.group == "trigger":
            trigger = n.id
        g.add_node(n.id, Wrapper(n, t, ports, journal, d), defer=t.deferred)
    g.add_edge(START, trigger)
    for n in d.nodes:
        t = registry.get(n.type, n.type_version)
        out_ports = t.output_ports(n.parameters)
        if not out_ports:
            g.add_edge(n.id, END)
            continue
        routes = {p: d.targets(n.id, p) for p in out_ports}

        def route(s: dict[str, Any], nid: str = n.id, routes: dict[str, list[str]] = routes) -> list[str] | str:
            env = cast(dict[str, Any], s.get(channel(nid)) or {})
            return routes.get(str(env.get("port")), []) or END

        g.add_conditional_edges(n.id, route, sorted({*[x for v in routes.values() for x in v], END}))
    return g.compile(checkpointer=checkpointer)


class CompiledCache:
    """Compiled graphs by digest: a digest names one definition forever, so nothing invalidates."""

    def __init__(self, registry: TypeRegistry, ports: EnginePorts, journal: Journal, checkpointer: Any) -> None:
        self.registry, self.ports, self.journal, self.checkpointer = registry, ports, journal, checkpointer
        self._graphs: dict[str, Any] = {}

    def get(self, d: WorkflowDefinition) -> Any:
        digest = d.digest()
        if digest not in self._graphs:
            self._graphs[digest] = compile_definition(
                d,
                self.registry,
                ports=self.ports,
                journal=self.journal,
                checkpointer=self.checkpointer,
            )
        return self._graphs[digest]
