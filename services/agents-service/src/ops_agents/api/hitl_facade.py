"""Runtime threads as the console's Cases runs and Reviews, on the console's own HTTP contract
(`apps/console/src/lib/api/cases-contract.ts` and the `reviews` area of `contract.ts`).

Every row is built here, joined with its state, journal, SLA timers and decisions, so the console renders what it gets
and never joins two lists. This is the human-in-loop facade until `hitl-service` exists; the routes move there then.

Decide then resume (`docs/architecture/service-map.md`): the decision is recorded first, keyed by the paused step's
interrupt id (the decision id), then the thread is resumed under a run id derived from it. A resume that fails leaves
the decision standing with `resumed_at` unset, and the next decide with the same decision retries the resume once.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict, cast

from langgraph.types import Command

from ops_access import can
from ops_agents.graphs.definition import WorkflowDefinition, option_declarations, option_name
from ops_service_kit import narrow
from ops_service_kit.errors import ApiError, Conflict, NotFound, ValidationFailed
from ops_service_kit.http import Json, JsonList, JsonValue
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger
from ops_store import isolation

from ..store.cases import CaseStore
from ..store.events import EventLog
from ..store.graphs import RunJournal, ThreadRow
from ..store.leases import LeaseHeldError
from ..store.review_assignments import ReviewAssignments
from ..store.review_sources import ReviewSources
from ..store.reviews import DecisionOut, ReviewStore
from ..store.timers import TimerStore
from . import engine_reviews, publish_reviews
from .agent_registry import ReviewPolicy, ReviewView, registry
from .auth import (
    Principal,
    caller_of,
    require_asker,
    require_not_own,
    require_reviews_decide,
    require_step_up,
    review_teams,
    step_up_ref,
    workspace_step_up,
)
from .deps import Runtime
from .option_inputs import apply_inputs, held_calls
from .review_sla import sla_hours
from .review_text import describe_call, operations
from .runs import Graph, config, definition, execute, graph_store, pending, resolve, resolve_rows
from .team_names import deciding_team
from .tool_access import policy_of

# Chat agents run on threads too; only workflows are runs on the Cases page.
log = get_logger("ops_agents.api.hitl_facade")
CASE_GRAPHS_EXCLUDED = {"agent_wrapper"}


def is_chat_graph(graph: str) -> bool:
    """Agent graphs: the shared wrapper and the per-agent `agent:<id>` graphs a publish registers. Cases never shows
    them; Reviews lists a chat's write approvals, decided there or in the conversation."""
    return graph in CASE_GRAPHS_EXCLUDED or graph.startswith("agent:")


class ThreadCall(TypedDict, total=False):
    """A write a paused thread step holds (`call`, an option's call, a `calls` entry): its operation, its input and the
    step key its approval binds to. The graphs write it (graphs/common.reply_call, the approval nodes, definition's
    levy calls); a workflow run's step holds the same keys (engine_reviews.ProposedCall), typed there for the stored
    check this checkpoint value is not read through."""

    tool: str
    input: Json
    step: str


class ThreadPayload(TypedDict, total=False):
    """What a paused thread step waits with (the interrupt's value in the LangGraph checkpoint): a workflow review
    (definition's human node, complex_workflow.human), a chat or agent node's write approval (the approval nodes) or
    an exhausted budget (metering.guard). A checkpoint can hold values that are not JSON and keys of any type, so the
    fields name the shape the graphs write and nothing here checks it: each read below behaves as it did on a dict."""

    kind: str
    node: str
    review_id: str
    to: str
    draft: JsonValue
    score: float
    attempts: int
    customer: Json
    error: JsonValue
    call: ThreadCall
    calls: dict[str, ThreadCall]
    options: list[JsonValue]
    ask_first: bool
    requested_by: JsonValue
    reviewer_role: JsonValue
    step_up: bool


class ChatReview(TypedDict):
    """A paused thread step as the console's `Review` (review_view), in reply order, then who it is assigned to and
    whether the caller may decide it, which the list and the routes add."""

    origin: Json
    id: JsonValue
    title: str
    customer: JsonValue
    workflowId: JsonValue
    workflowName: JsonValue
    agentSlug: JsonValue
    kind: str
    risk: str
    confidence: float
    proposal: str
    actionTool: JsonValue
    currency: str
    policy: ReviewPolicy
    slaMinutes: int | None
    approvals: list[str]
    status: str
    createdAt: JsonValue
    reasoning: list[str]
    evidence: list[Json]
    stepUp: bool
    amount: float | None
    options: list[Json] | None
    optionsError: str | None
    calls: dict[str, ThreadCall] | None
    error: JsonValue
    consequence: str | None
    actionFields: list[dict[str, str]]
    decidingTeam: dict[str, str | None] | None
    assignee: NotRequired[JsonValue]
    caseTitle: NotRequired[str | None]
    canDecide: NotRequired[bool]


# One review as GET /reviews/{id} and a decision answer it: a paused thread step, a run's review step, a publish
# request, or a decided thread review (its stored review, so JSON).
Review = ChatReview | engine_reviews.EngineReview | ReviewView | Json
# A review as the list reads it: also a run's review step as all_rows lists it, until expand builds it.
Listed = Review | engine_reviews.EngineRow


class ReviewStats(TypedDict):
    unassigned: int
    medianDecisionMinutes: int
    medianDecisionTrendMinutes: int
    approvedAsProposedRate: float
    decidedToday: int


class ReviewPage(TypedDict):
    """One page of Human Tasks (list_reviews), in reply order: the rows, where the page sits, the view's facets,
    the count per view and the queue's stats."""

    data: list[Listed]
    pagination: Json
    facets: dict[str, dict[str, int]]
    viewCounts: dict[str, int]
    stats: ReviewStats


class QueuePlace(TypedDict):
    """Where a review sits in a view (queue_place): None for position, previous and next when it is not in it."""

    position: int | None
    total: int
    previous: str | None
    next: str | None


class RunStep(TypedDict):
    """One step of a Cases run (`RunStep` in apps/console/src/lib/types/cases.ts), from its runs' journals."""

    nodeId: str
    label: str
    kind: str
    status: str
    durationMs: NotRequired[int]
    detail: NotRequired[Any]


class SummaryRow(TypedDict):
    """One case thread as the Cases views, counts, search and facets read it (`summary_rows`); `thread` is its row."""

    id: str
    workflowId: str
    subject: str
    state: str
    status: str
    startedAt: str
    durationMs: int
    queue: str | None
    slaMinutes: int | None
    slaDueAt: str | None
    parentThreadId: str | None
    thread: Json


class Paged[T](TypedDict):
    """One page of rows and where it sits (`page`)."""

    data: list[T]
    pagination: Json


class RunPage(TypedDict):
    """One page of Cases runs (list_runs), in reply order: the rows, where the page sits, and the view's facets and
    counts."""

    data: list[Json]
    pagination: Json
    facets: dict[str, dict[str, int]]
    viewCounts: dict[str, int]


STEP_KIND = {
    "human": "review",
    "send_reply": "action",
    "close": "end",
    **dict.fromkeys(["classify", "extract", "draft", "grade", "answer"], "agent"),
}


def _title(graph: str) -> str:
    return graph.replace("_", " ").capitalize()


def _get(d: object, key: str) -> Any:
    """`d[key]` for a JSON object from the journal or an interrupt, None for anything else. Unchecked: a checkpoint's
    value need not be JSON, and each caller reads it as it reads any other value."""
    return narrow.json_object(d).get(key)


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def _minutes_until(ts: str | None, now: datetime) -> int | None:
    due = _parse(ts)
    return None if due is None else int((due - now).total_seconds() // 60)


def _steps(runs: list[Json], waiting_at: list[str]) -> list[RunStep]:
    steps: list[RunStep] = [
        {"nodeId": "trigger", "label": "Started", "kind": "trigger", "status": "done", "durationMs": 0}
    ]
    for r in runs:
        if r["kind"] == "sla":
            continue
        open_steps: dict[str, list[RunStep]] = {}
        for e in cast(list[Json], r["events"]):
            # A journal's node is a step name; read unchecked, as each read below reads it.
            node = cast(str | None, e.get("node"))
            if e.get("event") == "node_start" and node:
                step: RunStep = {
                    "nodeId": node,
                    "label": _title(node),
                    "kind": STEP_KIND.get(node, "tool"),
                    "status": "done",
                }
                step["durationMs"] = 0
                steps.append(step)
                open_steps.setdefault(node, []).append(step)
            elif e.get("event") == "node_end" and node and open_steps.get(node):
                step = open_steps[node].pop(0)
                if _get(e.get("data"), "interrupted"):
                    step["status"] = "waiting"
            elif e.get("event") == "error":
                for left in open_steps.values():
                    for step in left:
                        step["status"] = "failed"
                        step["detail"] = _get(e.get("data"), "message")
    # A resume re-runs the paused node from its start, so only the latest step per waiting node is still waiting.
    for step in steps:
        if step["status"] == "waiting" and step is not next(
            s for s in reversed(steps) if s["nodeId"] == step["nodeId"]
        ):
            step["status"] = "done"
    if not waiting_at:
        for step in steps:
            if step["status"] == "waiting":
                step["status"] = "done"
    return steps


async def _decisions(rt: Runtime, thread_ids: list[str] | None = None) -> dict[str, DecisionOut]:
    """Latest decision per thread."""
    return await ReviewStore(graph_store(rt).engine).latest_decisions(thread_ids)


def requester_of(row: Json, payload: ThreadPayload | Json) -> str:
    """Who asked for the paused step: the person recorded on the interrupt when there is one, else the workflow
    itself (the process principal), which no person can be."""
    return str(payload.get("requested_by") or f"workflow:{row.get('graph')}")


CHAT_GRAPH = "agent_wrapper"


def _is_chat(row: Json) -> bool:
    """A chat thread (POST /chat/threads): its id is the conversation's, and its meta names the agent."""
    return bool(_meta(row).get("chat"))


def _meta(row: Json) -> Json:
    """A thread row's meta (a JSON object column; empty when unset). A value of another type fails the read, as
    reading a key of it did."""
    return narrow.an_object(row.get("meta") or {}, "a thread's meta")


class OptionsUnresolved(Exception):
    """A step's options cannot be read: the stored row names them but the workflow version, step or runtime cannot
    declare them. Listed with the reason, never a 500."""


async def resolved_options(
    rt: Runtime,
    row: Json,
    payload: ThreadPayload | Json,
    versions: Mapping[tuple[str, int], WorkflowDefinition] | None = None,
) -> list[Json]:
    """The declarations of the step's options. A row stores them as the step declared them at pause time; one paused
    before the declaration existed stores names only, which are resolved against the published version's step
    (the declaration is a property of the workflow version, not of the row) with the calls the row carries.
    `versions`: the workflow versions a list already read, so its rows read none again."""
    raw: JsonList = list(cast(JsonList, payload.get("options") or []))
    if not raw:
        return []
    if all(isinstance(o, dict) and "name" in o for o in raw):
        return [dict(cast(Json, o)) for o in raw]
    names = [option_name(o) for o in raw]
    if row.get("version") is None:
        raise OptionsUnresolved(f"The step offers {', '.join(names)} but the thread pins no workflow version.")
    try:
        graph, version = str(row["graph"]), int(cast(int, row["version"]))
        d = (versions or {}).get((graph, version)) or await definition(rt, graph, version)
    except NotFound as e:
        raise OptionsUnresolved(f"The thread's workflow version {row['graph']} v{row['version']} is gone.") from e
    node = d.node(str(payload.get("node") or ""))
    if node is None or node.kind != "human" or not node.config.get("options"):
        raise OptionsUnresolved(f"Step {payload.get('node')} of {d.name} v{d.version} declares no options.")
    if rt.graph_deps is None:
        raise OptionsUnresolved("Options cannot be declared without the graph runtime (no model configured).")
    calls: dict[str, Json] = dict(cast(dict[str, Json], payload.get("calls") or {}))
    declared = await option_declarations(rt.graph_deps, list(node.config["options"]), calls)
    by_name = {str(o["name"]): o for o in declared}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise OptionsUnresolved(
            f"Option {', '.join(missing)} of the paused step is not in {d.name} v{d.version}'s declaration."
        )
    return [by_name[n] for n in names]


async def interrupt_view(rt: Runtime, row: Json, interrupt: Json) -> Json:
    """The pending interrupt as GET state serves it: a step's options as declarations (resolved_options), or the
    names it stored with `optionsError` saying why they could not be declared."""
    payload: Json = dict(cast(Json, interrupt.get("payload") or {}))
    if not payload.get("options"):
        return interrupt
    try:
        payload["options"] = cast(JsonList, await resolved_options(rt, row, payload))
    except OptionsUnresolved as e:
        payload["optionsError"] = str(e)
    return {**interrupt, "payload": payload}


async def _needs_step_up(rt: Runtime, payload: ThreadPayload | Json) -> bool:
    """Approving needs a step-up when the operation asks for one (its policy's `stepUp`, which two approvers imply).
    A step with options needs one when any option's call does."""
    raw_listed: JsonList = list(cast(JsonList, payload.get("options") or []))
    listed_options: list[Json] = [dict(o) for o in raw_listed if isinstance(o, dict)]
    calls: list[object] = [payload.get("call"), *(o.get("call") for o in listed_options)]
    for tool in {str(_get(c, "tool")) for c in calls if _get(c, "tool")}:
        if (await policy_of(rt, tool)).step_up:
            return True
    return bool(payload.get("step_up"))


@dataclass(frozen=True)
class PageReads:
    """What `run_row` reads besides the checkpoint, for a whole page of threads: each thread's graph (or the error
    resolving it raised), its latest decision and its runs' journals, oldest first."""

    graphs: dict[str, Graph | ApiError]
    decisions: dict[str, DecisionOut]
    journals: dict[str, list[RunJournal]]


async def page_reads(rt: Runtime, threads: list[ThreadRow]) -> PageReads:
    """The graphs, decisions and run journals of `threads` in a fixed number of statements, so a page's reads do not
    grow with its rows."""
    ids = [t.id for t in threads]
    journals: dict[str, list[RunJournal]] = {}
    for run in await graph_store(rt).run_events(ids):
        journals.setdefault(run.thread_id, []).append(run)
    return PageReads((await resolve_rows(rt, threads)).graphs, await _decisions(rt, ids), journals)


async def run_row(summary: SummaryRow, reads: PageReads) -> Json:
    """One thread as a Cases RunRow (`RunRow` in apps/console/src/lib/types/cases.ts). State, status, subject, queue
    and SLA come from its summary row (`summary_rows`), as the list's do; this adds what only the checkpoint and the
    journal hold: the steps, the waiting call, the error and the trigger. Raises the error resolving its graph
    raised (a version removed, a digest changed)."""
    row = summary["thread"]
    thread_id = cast(str, row["id"])
    graph = reads.graphs[thread_id]
    if isinstance(graph, ApiError):
        raise graph
    snap = await graph.aget_state(config(thread_id))
    waiting = summary["state"] == "waiting"
    interrupts = pending(snap)
    work = [r for r in reads.journals.get(thread_id, []) if r.kind != "sla"]
    decision = reads.decisions.get(thread_id)
    values: Json = snap.values or {}
    email = cast(Json, values.get("email") or {})
    events = work[-1].events if work else []
    error = next((_get(e.get("data"), "message") for e in events if e.get("event") == "error"), None)
    payload: Json = cast(Json, interrupts[0]["payload"]) if waiting and interrupts else {}
    approved = 1 if decision and decision.decision == "approved" and decision.resumed_at else 0
    graph_name, meta = cast(str, row["graph"]), cast(Json, row["meta"])
    return {
        "id": row["id"],
        "workflowId": row["graph"],
        "workflowName": meta.get("workflowName") or _title(graph_name),
        "version": row["version"] or 1,
        "subject": summary["subject"],
        "status": summary["status"],
        "startedAt": summary["startedAt"],
        "durationMs": summary["durationMs"],
        **({"reviewId": row["id"]} if waiting else {}),
        **({"error": error} if summary["state"] == "failed" and error else {}),
        **_trigger(meta or {}, email),
        "steps": cast(
            JsonList, _steps([{"kind": r.kind, "events": cast(JsonList, r.events)} for r in work], list(snap.next))
        ),
        "state": summary["state"],
        "waitingOn": "Reviewers" if waiting else None,
        "queue": summary["queue"],
        "assignee": None,
        "slaDueAt": summary["slaDueAt"],
        "slaMinutes": summary["slaMinutes"],
        "actionsApproved": approved,
        "actionsPending": 1 if payload.get("call") or payload.get("options") else 0,
        "caseId": None,
        "parentThreadId": row.get("parent_thread_id"),
        "children": cast(JsonList | None, children_view(values, meta or {})),
    }


def children_view(values: Mapping[str, JsonValue], meta: Mapping[str, JsonValue]) -> list[Json] | None:
    """A parent's child cases with their current outcome: the list the run wrote (`children` in its state, frozen at
    open time) with each child's finish, written to the parent's meta by `child_runs.tell_parent`, laid over it."""
    # `dict()` of each entry, as before: an entry that is not an object raises or copies its pairs.
    raw_opened: JsonList = list(cast(JsonList, values.get("children") or []))
    raw_finished: JsonList = list(cast(JsonList, meta.get("children") or []))
    opened: list[Json] = [dict(cast(Json, c)) for c in raw_opened]
    finished: list[Json] = [dict(cast(Json, c)) for c in raw_finished]
    if not opened and not finished:
        return None
    by_id = {c.get("threadId"): c for c in opened}
    for f in finished:
        by_id[f.get("threadId")] = {**by_id.get(f.get("threadId"), {}), **f}
    return list(by_id.values())


def _trigger(meta: Json, email: Json) -> dict[str, str]:
    """What started the run when it was not its own trigger: an agent calling the workflow as a tool."""
    if meta.get("startedBy") == "agent":
        return {"trigger": f"Started by agent {meta.get('agentName') or ''}".rstrip()}
    return {"trigger": f"From {email['sender']}"} if email.get("sender") else {}


def _done_today(r: SummaryRow, now: datetime) -> bool:
    if r["state"] not in ("done", "failed"):
        return False
    started = _parse(r["startedAt"])
    finished = started.timestamp() + r["durationMs"] / 1000 if started else 0
    return datetime.fromtimestamp(finished, UTC).date() == now.date()


RUN_VIEWS: dict[str, Callable[[SummaryRow, datetime], bool]] = {
    "needs_person": lambda r, now: r["state"] == "waiting",
    "open": lambda r, now: r["state"] in {"running", "waiting"},
    "past_sla": lambda r, now: r["state"] in ("running", "waiting") and (r["slaMinutes"] or 0) < 0,
    "done_today": _done_today,
}


def _facets(rows: Sequence[SummaryRow] | Sequence[Listed], columns: list[str]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {c: {} for c in columns}
    for r in rows:
        for c in columns:
            if (value := r.get(c)) is not None:
                out[c][str(value)] = out[c].get(str(value), 0) + 1
    return out


def page[T](rows: list[T], page_no: int, size: int) -> Paged[T]:
    total = len(rows)
    pages = max(1, -(-total // size))
    start = (page_no - 1) * size
    meta: Json = {"page": page_no, "pageSize": size, "total": total, "totalPages": pages}
    meta |= {"hasNext": page_no < pages, "hasPrev": page_no > 1}
    return {"data": rows[start : start + size], "pagination": meta}


async def _resolvable(rt: Runtime) -> set[str]:
    """Graph names a thread can run on: the compiled graphs and every published definition."""
    assert rt.graph_store is not None
    return set(await rt.graph_store.latest_versions()) | set(rt.graphs)


async def summary_rows(rt: Runtime, now: datetime, only: str | None = None) -> list[SummaryRow]:
    """Every case thread (or `only` that one) as the fields the Cases views, counts, search and facets read, from
    three queries in all. These are the only source of a row's state, status, subject, queue and SLA: the list and
    the detail page both take them from here, so they cannot disagree. Building full rows (`run_row`: checkpoint,
    journal, timers per thread) for every thread made the list cost seconds with a thousand threads; `list_runs`
    builds them for the page only."""
    resolvable = await _resolvable(rt)
    # As mappings: each summary row carries its thread as stored ("thread"), and the reads below take it by key.
    threads = [
        t
        for t in [r.model_dump() for r in await graph_store(rt).thread_rows(None)]
        if not is_chat_graph(t["graph"]) and t["graph"] in resolvable and (only is None or t["id"] == only)
    ]
    runs = await graph_store(rt).run_summaries(only)
    # A thread whose last run failed may still be paused (a failed resume leaves the interrupt in place); its
    # checkpoint says which. Every other status says it directly, so only these few threads are read.
    unsure = [t["id"] for t in threads if t["status"] in ("error", "lease_lost")]
    paused = {t["id"] for t in threads if t["status"] == "interrupted"} | await _still_paused(rt, unsure)
    due = await _open_sla_due(rt, sorted(paused))
    rows: list[SummaryRow] = []
    for t in threads:
        work = [r for r in runs.get(t["id"], []) if r.kind != "sla"]
        last = work[-1] if work else None
        waiting = t["id"] in paused and t["status"] != "busy"
        failed = t["status"] == "error" or (last is not None and last.status == "error")
        state = "running" if t["status"] == "busy" else "waiting" if waiting else "failed" if failed else "done"
        started, finished = _parse(t["created_at"]), _parse(last.finished_at if last else None)
        end = now if state in ("running", "waiting") or finished is None else finished
        # The email in the thread's state is the one the latest input run brought.
        email: Json = {}
        for r in reversed(work):
            given = narrow.an_object(narrow.an_object(r.input or {}, "a run's input").get("input") or {}, "its input")
            found_email = given.get("email")
            if found_email:
                email = narrow.an_object(found_email, "the run's email")
                break
        sla_due = due.get(t["id"]) if waiting else None
        rows.append(
            {
                "id": t["id"],
                "workflowId": t["graph"],
                "subject": cast(str, email.get("subject") or t["meta"].get("subject") or _title(t["graph"])),
                "state": state,
                "status": {"running": "running", "waiting": "waiting_review", "failed": "failed", "done": "completed"}[
                    state
                ],
                "startedAt": t["created_at"],
                "durationMs": int((end - started).total_seconds() * 1000) if started else 0,
                "queue": "Reviews" if waiting else None,
                "slaMinutes": _minutes_until(sla_due, now),
                "slaDueAt": sla_due,
                "parentThreadId": t.get("parent_thread_id"),
                "thread": t,
            }
        )
    return rows


async def _still_paused(rt: Runtime, thread_ids: list[str]) -> set[str]:
    out: set[str] = set()
    for tid in thread_ids:
        try:
            _, graph = await resolve(rt, tid)
        except (NotFound, Conflict):
            continue
        if pending(await graph.aget_state(config(tid))):
            out.add(tid)
    return out


async def _open_sla_due(rt: Runtime, thread_ids: list[str]) -> dict[str, str]:
    """The time each thread's SLA lapses: its earliest open breach timer, else its earliest open timeout."""
    found = await TimerStore(rt.db).open_due(thread_ids)
    return {tid: (k.get("breach") or k["timeout"]).isoformat() for tid, k in found.items()}


async def list_runs(
    rt: Runtime, *, view: str, filters: dict[str, list[str]], search: str | None, page_no: int, size: int
) -> RunPage:
    now = datetime.now(UTC)
    if view not in RUN_VIEWS:
        raise ValidationFailed(f"Unknown view {view}.")
    rows = await summary_rows(rt, now)
    counts = {name: sum(1 for r in rows if match(r, now)) for name, match in RUN_VIEWS.items()}
    in_view = [r for r in rows if RUN_VIEWS[view](r, now)]
    if search:
        needle = search.lower()
        in_view = [r for r in in_view if needle in r["subject"].lower() or needle in r["id"].lower()]
    facets = _facets(in_view, ["workflowId", "state", "queue"])
    for column, wanted in filters.items():
        if wanted:
            in_view = [r for r in in_view if str(r.get(column)) in wanted]
    paged = page(in_view, page_no, size)
    reads = await page_reads(rt, [ThreadRow.model_validate(r["thread"]) for r in paged["data"]])
    full: list[Json] = []
    for r in paged["data"]:
        try:
            full.append(await run_row(r, reads))
        except (NotFound, Conflict) as e:
            # Its graph cannot be compiled (a version removed, a digest changed): leave it out, not the whole list.
            log.warning("case_row_skipped", thread=r["id"], graph=r["workflowId"], error=e.code)
    return {"data": full, "pagination": paged["pagination"], "facets": facets, "viewCounts": counts}


async def get_run(rt: Runtime, thread_id: str) -> Json:
    now = datetime.now(UTC)
    found = await summary_rows(rt, now, only=thread_id)
    if not found:
        raise NotFound("Run")
    return await run_row(found[0], await page_reads(rt, [ThreadRow.model_validate(found[0]["thread"])]))


# ── Reviews ──


class Known:
    """What building reviews reads once for all their threads: each one's SLA deadline, its approvers by (thread,
    step) and the workflow versions the threads pin, so a list's reads do not grow with its rows."""

    def __init__(
        self,
        due: dict[str, str],
        approvals: dict[tuple[str, str], list[str]],
        versions: Mapping[tuple[str, int], WorkflowDefinition],
    ) -> None:
        self.due = due
        self.approvals = approvals
        self.versions = versions


async def known_for(
    rt: Runtime, ids: list[str], versions: Mapping[tuple[str, int], WorkflowDefinition] | None = None
) -> Known:
    """`Known` for the threads `ids` names, in one statement per kind; `ids` is bounded by the list's rows per
    source."""
    approvals = await ReviewStore(graph_store(rt).engine).approvers_of(ids)
    return Known(await _open_sla_due(rt, ids), approvals, versions or {})


async def review_view(rt: Runtime, row: Json, interrupt: Json, now: datetime, known: Known | None = None) -> ChatReview:
    """A paused review step as a console `Review`; `status` is pending until a decision is recorded. `known`: what a
    list read once for all its rows; one review reads its own."""
    known = known or await known_for(rt, [str(row["id"])])
    # The checkpoint's value as it is: a payload that is not an object fails its first read, as it did.
    payload = cast(ThreadPayload, interrupt["payload"])
    call = cast(Json, payload.get("call") or {})
    policy = await policy_of(rt, cast(str, call["tool"])) if call.get("tool") else None
    access = policy.access if policy else "unknown"
    two = bool(policy and policy.approvers > 1)
    due = known.due.get(str(row["id"]))
    chat = _is_chat(row)
    meta = cast(Json, row["meta"])
    agent_name = str(meta.get("agentName") or meta.get("agentId") or "")
    options_error: str | None = None
    try:
        options = await resolved_options(rt, row, payload, known.versions)
    except OptionsUnresolved as e:
        options, options_error = [], str(e)
    payload = cast(ThreadPayload, {**payload, "options": options})
    for o in options:
        # Per option, so a form asks for the step-up only when the chosen call needs it.
        o["stepUp"] = await _needs_step_up(rt, {"call": o.get("call")})
    subject = str(meta.get("subject") or "")
    if chat and call.get("tool"):
        title = f"Run {call['tool']} for {agent_name}"
    elif payload.get("to"):
        title = f"Send reply to {payload.get('to')}"
    elif subject:
        title = subject
    else:
        title = f"Review {_title(cast(str, row['graph']))}"
    # What the proposal would move: the first option's (or the call's) input named amount, as the operation spells it.
    proposals: list[Json] = [dict(cast(Json, o.get("call") or {})) for o in options] + ([call] if call else [])
    amount = _amount_of(proposals)
    # The step's own call in words, as a workflow review words it (engine_reviews.view): what approving does and sends.
    described = await describe_call(rt, call, currency=None, money_key=None) if call.get("tool") else None
    customer: Json = dict(payload.get("customer") or {})
    origin: Json = {"kind": "chat", "threadId": row["id"], "agentName": agent_name} if chat else {"kind": "workflow"}
    return {
        "origin": origin,
        "id": row["id"],
        "title": title,
        "customer": payload.get("to") or customer.get("name") or customer.get("id") or "",
        "workflowId": row["graph"],
        "workflowName": meta.get("workflowName") or _title(cast(str, row["graph"])),
        "agentSlug": row["graph"],
        "kind": "approval",
        "risk": "high" if two else "medium" if access == "write" else "low",
        "confidence": float(payload.get("score") or 0),
        "proposal": str(payload.get("draft") or ""),
        "actionTool": call.get("tool") or "",
        "currency": "USD",
        "policy": {
            "id": f"{row['graph']}:{payload.get('kind', 'review')}",
            "name": "Human review",
            "condition": "Every outgoing reply" if call.get("tool") == "send_reply" else "Every paused step",
            "reviewers": "Reviewers",
            "sla": "Per workflow",
            "onTimeout": "Per workflow",
            "fourEyes": two,
        },
        # None when the step set no SLA: a row then says so instead of "0m left".
        "slaMinutes": _minutes_until(due, now) if due else None,
        "approvals": known.approvals.get((str(row["id"]), str(call["step"])), []) if call.get("step") else [],
        "status": "pending",
        "createdAt": row["updated_at"],
        "reasoning": _reasoning(payload),
        "evidence": [{"kind": "tool", "label": call["tool"], "detail": str(call.get("input") or {})}] if call else [],
        "stepUp": await _needs_step_up(rt, payload),
        "amount": amount,
        "options": options or None,
        "optionsError": options_error,
        "calls": payload.get("calls") or None,
        "error": payload.get("error") or None,
        "consequence": (described["consequence"] or described["sentence"]) if described else None,
        "actionFields": described["fields"] if described else [],
        # Who decides it, as check_thread_decider checks: a write's approving team, else the thread's team.
        "decidingTeam": await deciding_team(rt, cast(str | None, row.get("team_id"))),
    }


def _amount_of(proposals: list[Json]) -> float | None:
    """The first proposed call input named amount (as the operation spells it), when it is a number."""
    for proposal in proposals:
        inputs: Json = dict(cast(Json, proposal.get("input") or {}))
        for key, value in inputs.items():
            if key.replace("_", "").casefold().endswith("amount") and isinstance(value, int | float):
                return float(value)
    return None


def _reasoning(payload: ThreadPayload | Json) -> list[str]:
    out: list[str] = []
    if payload.get("score") is not None:
        out.append(f"The draft was graded {payload.get('score')}.")
    if payload.get("attempts"):
        out.append(f"Drafted in {payload.get('attempts')} attempts.")
    return out


def _decided(d: DecisionOut) -> Json:
    review: Json = dict(d.review)
    # A decision recorded before reviews named their origin was a workflow's: chat approvals were not listed then.
    review.setdefault("origin", {"kind": "workflow"})
    resume: Json = dict(cast(Json, review.get("resume") or {}))
    return review | {
        "status": d.decision,
        "decidedBy": d.decided_by,
        "decidedAt": d.decided_at,
        "decisionReason": d.reason,
        "option": resume.get("option"),
        "stepUpRef": d.step_up_ref,
    }


@dataclass(frozen=True)
class HeldStep:
    """A waiting thread review's thread and the paused step's payload (the interrupt's value, JSON in the checkpoint),
    as the list read them."""

    thread: ThreadRow
    payload: Mapping[str, JsonValue]


# The list's waiting thread reviews, by review id.
Held = dict[str, HeldStep]


@dataclass(frozen=True)
class ReviewReads:
    """What the review list reads from this service's own tables before any review is built: the waiting graph
    threads with their decisions, the workflow versions they pin, and the engine's review steps."""

    threads: list[tuple[Json, Json | None, DecisionOut | None]]
    versions: dict[tuple[str, int], WorkflowDefinition]
    engine: engine_reviews.RowReads | None


async def read_reviews(rt: Runtime) -> ReviewReads:
    """The local reads that say which tools and teams the reviews name, for a caller that holds one transaction."""
    threads, versions = await _thread_reviews(rt)
    return ReviewReads(threads, versions, await engine_reviews.read_rows(rt))


async def ask_outside(rt: Runtime, reads: ReviewReads) -> None:
    """Asks tools-service for each held write's policy, and warms the deadline policy, the tool directory and the team
    names the reviews are worded with, so building them makes none of those calls while a transaction is open. Each
    answer is kept for the request by `one_read_per_tool` and the request-wide directory read; a caller outside the
    first asks again where it builds."""
    tools: set[str] = set()
    teams: set[str] = set()
    for row, waiting, _ in reads.threads:
        if not waiting:
            continue
        if row.get("team_id"):
            teams.add(str(row["team_id"]))
        payload = waiting["payload"]
        raw_options: list[object] = list(_get(payload, "options") or [])
        calls: list[object] = [_get(payload, "call"), *(_get(o, "call") for o in raw_options)]
        by_option: Any = _get(payload, "calls") or {}
        calls += list(by_option.values())
        tools |= {str(_get(c, "tool")) for c in calls if _get(c, "tool")}
    if reads.engine is not None:
        tools |= set(reads.engine.tools)
        teams |= {str(run["team_id"]) for run, _ in reads.engine.steps if run.get("team_id")}
    await engine_reviews.ask_policies(rt, sorted(tools))
    await sla_hours(rt)
    await operations(rt)
    for team in sorted(teams):
        await deciding_team(rt, team)


async def read_then_ask(rt: Runtime) -> ReviewReads:
    """`read_reviews` in its own transaction, then `ask_outside` with none open: the first of the two transactions
    a review list or the Overview holds, the second building the reviews from these reads."""
    async with isolation.request_transaction():
        reads = await read_reviews(rt)
    await ask_outside(rt, reads)
    return reads


async def build_reviews(rt: Runtime, reads: ReviewReads) -> tuple[list[Listed], Held]:
    """Every review the selected team may see, each with who it is assigned to. A workflow step is the row
    engine_reviews.all_rows makes, enough to count, filter and page on; `engine_reviews.expand` builds the full review
    of the rows a caller shows. Also each waiting thread review's thread and step payload, so the list says who may
    decide each without reading its thread again."""
    now = datetime.now(UTC)
    out: list[Listed] = []
    held: Held = {}
    threads = reads.threads
    known = await known_for(rt, [str(row["id"]) for row, waiting, _ in threads if waiting], reads.versions)
    for row, waiting, d in threads:
        if waiting:
            out.append(await review_view(rt, row, waiting, now, known))
            held[str(row["id"])] = HeldStep(ThreadRow.model_validate(row), cast(Json, waiting["payload"]))
        elif d is not None:
            out.append(_decided(d))
    # Agent and workflow publish requests are reviews too: one list, counted and filtered with the rest.
    rows = out + await publish_reviews.all_views(rt) + await engine_reviews.build_rows(rt, reads.engine)
    assigned = await ReviewAssignments(rt.db).current([str(r["id"]) for r in rows])
    listed: list[Listed] = []
    for r in rows:
        with_who = r.copy()
        with_who["assignee"] = assigned.get(str(r["id"]), r.get("assignee"))
        listed.append(with_who)
    return listed, held


async def all_reviews(rt: Runtime) -> tuple[list[Listed], Held]:
    """`build_reviews` after its reads, for a caller that holds no transaction of its own."""
    return await build_reviews(rt, await read_then_ask(rt))


async def _places(rt: Runtime) -> list[Json]:
    """all_reviews by id and status alone, in its order, for a task's place in its queue: no review is built."""
    threads: list[Json] = [
        {"id": row["id"], "status": "pending" if waiting or d is None else d.decision}
        for row, waiting, d in (await _thread_reviews(rt))[0]
    ]
    published: list[Json] = [{"id": r["id"], "status": r["status"]} for r in await publish_reviews.all_views(rt)]
    return threads + published + await engine_reviews.all_places(rt)


async def _thread_reviews(
    rt: Runtime,
) -> tuple[
    list[tuple[Json, Json | None, DecisionOut | None]],
    dict[tuple[str, int], WorkflowDefinition],
]:
    """Each graph thread that holds a review, with the interrupt it waits on (None once decided) and its decision, of
    the newest `review_list_rows_per_source` threads; their decisions only are read. Also the workflow versions their
    graphs were resolved from, read once for every thread."""
    out: list[tuple[Json, Json | None, DecisionOut | None]] = []
    capped = await ReviewSources(graph_store(rt).engine).threads(rt.settings.review_list_rows_per_source)
    decisions = await _decisions(rt, [t.id for t in capped])
    # A chat's write approval is listed, so a second approver need not be sent a chat link; other agent graph threads
    # take no review here yet.
    threads = [
        r for r in (t.model_dump() for t in capped) if not (is_chat_graph(cast(str, r["graph"])) and not _is_chat(r))
    ]
    # A run marks its thread idle only when it ends with nothing pending (runs.execute), so an idle thread waits on no
    # review and its graph and checkpoint are not read: only its decision, if any, is listed.
    listed = {r["id"] for r in threads if r["status"] != "idle"}
    resolved = await resolve_rows(rt, [t for t in capped if t.id in listed])
    for row in threads:
        d = decisions.get(row["id"])
        if row["status"] == "idle":
            if d is not None:
                out.append((row, None, d))
            continue
        graph = resolved.graphs[row["id"]]
        if isinstance(graph, ApiError):
            # A thread whose graph cannot be resolved now (no model configured, a version gone) is left out; the
            # rest of the queue still lists rather than refusing every review.
            log.warning("review_row_skipped", thread=row["id"], graph=row["graph"], error=graph.code)
            continue
        waiting = pending(await graph.aget_state(config(row["id"])))
        if waiting and not (d and d.decision_id == waiting[0]["id"]):
            out.append((row, waiting[0], d))
        elif d is not None:
            out.append((row, None, d))
    return out, resolved.versions


async def with_assignee(rt: Runtime, review: Review) -> Review:
    """One review with who it is assigned to now."""
    assigned = await ReviewAssignments(rt.db).current([str(review["id"])])
    out = review.copy()
    out["assignee"] = assigned.get(str(review["id"]), review.get("assignee"))
    return out


def _elapsed_minutes(start: str, end: str) -> float:
    a, b = _parse(start), _parse(end)
    return (b - a).total_seconds() / 60 if a and b else 0.0


REVIEW_VIEWS: dict[str, Callable[[Listed], bool]] = {
    # Open and assigned to the caller; list_reviews puts the caller's names in.
    "mine": lambda r: False,
    "open": lambda r: r["status"] in ("pending", "in_review"),
    # A review whose step set no SLA (slaMinutes None) is never overdue.
    "overdue": lambda r: r["status"] in ("pending", "in_review") and cast(float, r.get("slaMinutes") or 0) < 0,
    "resolved": lambda r: r["status"] in ("approved", "rejected", "returned", "withdrawn"),
    "all": lambda r: True,
}


GROUPS = frozenset({"case"})


def by_case(rows: list[Listed]) -> list[Listed]:
    """Rows grouped by case: each case's rows together, the case whose soonest deadline is soonest first, then
    the rows inside a case by their own deadline. A row on no case is its own group. Rows with no deadline (`dueAt`
    is set on workflow steps only) sort last, keeping the order they came in, so the list and the place agree."""
    first: dict[str, int] = {}
    soonest: dict[str, str] = {}
    for i, r in enumerate(rows):
        group = str(r.get("caseId") or r["id"])
        first.setdefault(group, i)
        due = cast(str | None, r.get("dueAt"))
        if due and (group not in soonest or due < soonest[group]):
            soonest[group] = due

    def key(item: tuple[int, Listed]) -> tuple[bool, str, int, bool, str, int]:
        i, r = item
        group = str(r.get("caseId") or r["id"])
        due = cast(str | None, r.get("dueAt"))
        return (group not in soonest, soonest.get(group, ""), first[group], not due, due or "", i)

    return [r for _, r in sorted(enumerate(rows), key=key)]


def _grouped(rows: list[Listed], group: str | None) -> list[Listed]:
    if group is None:
        return rows
    if group not in GROUPS:
        raise ValidationFailed(f"Unknown group {group}; use case.")
    return by_case(rows)


async def list_reviews(
    rt: Runtime,
    *,
    view: str,
    filters: dict[str, list[str]],
    search: str | None,
    page_no: int,
    size: int,
    me: frozenset[str] = frozenset(),
    group: str | None = None,
    teams: list[str],
    approver: Principal | None = None,
    reads: ReviewReads | None = None,
) -> ReviewPage:
    """`me` is every name the caller is recorded by (email, name); Assigned to me lists open reviews assigned to one.
    `group="case"` orders the view by case and names each row's case from `teams`, the teams the caller reads in.
    With `approver`, each row of the page says whether they may decide it now (`canDecide`). `reads` (from
    `read_then_ask`) lets the caller hold one transaction for everything after the outside calls."""
    if view not in REVIEW_VIEWS:
        raise ValidationFailed(f"Unknown view {view}.")

    def mine(r: Listed) -> bool:
        return REVIEW_VIEWS["open"](r) and r.get("assignee") in me

    views = REVIEW_VIEWS | {"mine": mine}
    rows, held = await build_reviews(rt, reads) if reads is not None else await all_reviews(rt)
    counts = {name: sum(1 for r in rows if match(r)) for name, match in views.items() if name != "all"}
    today = datetime.now(UTC).date()
    decided = [r for r in rows if r.get("decidedAt")]
    # A decided row's decidedAt is set (the filter above), so get() reads it as indexing did.
    minutes = sorted(_elapsed_minutes(cast(str, r["createdAt"]), cast(str, r.get("decidedAt"))) for r in decided)
    stats: ReviewStats = {
        "unassigned": sum(1 for r in rows if REVIEW_VIEWS["open"](r) and not r.get("assignee")),
        "medianDecisionMinutes": round(minutes[len(minutes) // 2]) if minutes else 0,
        "medianDecisionTrendMinutes": 0,
        "approvedAsProposedRate": round(sum(1 for r in decided if r["status"] == "approved") / len(decided), 2)
        if decided
        else 0,
        "decidedToday": sum(1 for r in decided if cast(str, r.get("decidedAt"))[:10] == today.isoformat()),
    }
    in_view = [r for r in rows if views[view](r)]
    if search:
        # A typed task's title comes from its task, so a search reads the full reviews it matches against.
        needle = search.lower()
        in_view = await engine_reviews.expand(rt, in_view)
        in_view = [
            r for r in in_view if needle in cast(str, r["title"]).lower() or needle in cast(str, r["id"]).lower()
        ]
    facets = _facets(in_view, ["risk", "workflowId", "kind", "agentSlug", "status"])
    for column, wanted in filters.items():
        if wanted:
            in_view = [r for r in in_view if str(r.get(column)) in wanted]
    shown = page(_grouped(in_view, group), page_no, size)
    shown["data"] = await engine_reviews.expand(rt, shown["data"])
    if group == "case":
        # One read for the page; a case of a team the caller is not in is left out, so its row has no title.
        ids = sorted({str(r.get("caseId")) for r in shown["data"] if r.get("caseId")})
        named = await CaseStore(rt.db).summaries(ids, teams)
        titled: list[Listed] = []
        for r in shown["data"]:
            with_case = r.copy()
            with_case["caseTitle"] = case.subject if (case := named.get(str(r.get("caseId")))) else None
            titled.append(with_case)
        shown["data"] = titled
    if approver is not None:
        decidable: list[Listed] = []
        for r in shown["data"]:
            with_say = r.copy()
            with_say["canDecide"] = await _may_decide(rt, approver, str(r["id"]), r.get("status"), held)
            decidable.append(with_say)
        shown["data"] = decidable
    return {
        "data": shown["data"],
        "pagination": shown["pagination"],
        "facets": facets,
        "viewCounts": counts,
        "stats": stats,
    }


async def _may_decide(rt: Runtime, approver: Principal, review_id: str, status: object, held: Held) -> bool:
    """can_decide for a listed review: a waiting thread review is checked on the thread row and step the list read,
    as can_decide checks them after reading both again; any other review asks can_decide."""
    if status not in ("pending", "in_review"):
        return False
    if review_id not in held:
        return await can_decide(rt, approver, review_id)
    step = held[review_id]
    payload = dict(step.payload)
    try:
        await check_thread_decider(rt, approver, step.thread.model_dump(), payload, held_calls(payload))
    except ApiError:
        return False
    return True


async def queue_place(
    rt: Runtime, review_id: str, view: str = "open", group: str | None = None, reads: ReviewReads | None = None
) -> QueuePlace:
    """Where a review sits in a view, in the order Human Tasks lists it: its position, the total, and the reviews either
    side, so a task's page says "5 of 24" and steps through the queue without the console fetching it."""
    if view not in REVIEW_VIEWS:
        raise ValidationFailed(f"Unknown view {view}.")
    # Overdue reads each review's deadline, which only a built review has; the other views need the id and status.
    if view != "overdue":
        rows = await _places(rt)
    else:
        rows = (await build_reviews(rt, reads))[0] if reads is not None else (await all_reviews(rt))[0]
    ids = [str(r["id"]) for r in _grouped([r for r in rows if REVIEW_VIEWS[view](r)], group)]
    # A run's id names the review it waits on (`<run>:<step>:<iteration>`), as GET /reviews/{id} reads it.
    if review_id not in ids:
        review_id = next((i for i in ids if i.startswith(f"{review_id}:")), review_id)
    if review_id not in ids:
        return {"position": None, "total": len(ids), "previous": None, "next": None}
    at = ids.index(review_id)
    return {
        "position": at + 1,
        "total": len(ids),
        "previous": ids[at - 1] if at > 0 else None,
        "next": ids[at + 1] if at + 1 < len(ids) else None,
    }


async def get_review(rt: Runtime, thread_id: str) -> Review:
    """One thread's review, chat-agent threads included: decide serves every review-owned interrupt. A publish
    request's id (AGP-…, WFP-…) answers with that request."""
    if publish_reviews.is_request_id(thread_id):
        return await publish_reviews.get(rt, thread_id)
    if engine_reviews.is_engine_id(thread_id):
        return await engine_reviews.get(rt, thread_id)
    row, step, d = await _thread_step(rt, thread_id)
    if step is not None:
        return await review_view(rt, row, step, datetime.now(UTC))
    assert d is not None
    return _decided(d)


async def _thread_step(rt: Runtime, thread_id: str) -> tuple[Json, Json | None, DecisionOut | None]:
    """A graph thread's row, the step it waits on (None once decided) and its decision; not found when it holds no
    review."""
    found = await graph_store(rt).thread_row(thread_id)
    if found is None:
        raise NotFound("Review")
    row = found.model_dump()
    _, graph = await resolve(rt, thread_id)
    waiting = pending(await graph.aget_state(config(thread_id)))
    d = (await _decisions(rt, [thread_id])).get(thread_id)
    if waiting and not (d and d.decision_id == waiting[0]["id"]):
        return row, waiting[0], d
    if d is not None:
        return row, None, d
    raise NotFound("Review")


async def review_for(rt: Runtime, approver: Principal, thread_id: str) -> Review:
    """`get_review` with who it is assigned to and whether `approver` may decide it now (`canDecide`). A graph thread's
    review takes two transactions: the thread and its step, then, once tools-service has answered with none open, the
    review built from them."""
    if publish_reviews.is_request_id(thread_id) or engine_reviews.is_engine_id(thread_id):
        review = await with_assignee(rt, await get_review(rt, thread_id))
        waiting = review.get("status") in ("pending", "in_review")
        review["canDecide"] = waiting and await can_decide(rt, approver, str(review["id"]))
        return review
    async with isolation.request_transaction():
        row, step, d = await _thread_step(rt, thread_id)
        if step is None:
            assert d is not None
            decided = await with_assignee(rt, _decided(d))
            decided["canDecide"] = False
            return decided
    await ask_outside(rt, ReviewReads([(row, step, d)], {}, None))
    async with isolation.request_transaction():
        review = await with_assignee(rt, await review_view(rt, row, step, datetime.now(UTC)))
        held = {str(row["id"]): HeldStep(ThreadRow.model_validate(row), cast(Json, step["payload"]))}
        review["canDecide"] = await _may_decide(rt, approver, str(review["id"]), review["status"], held)
        return review


async def decide(
    rt: Runtime,
    approver: Principal,
    thread_id: str,
    *,
    decision: str,
    reason: str | None,
    step_up_token: str | None,
    amount: float | None = None,
    inputs: Json | None = None,
    for_chat: bool = False,
) -> Review:
    """Decides as `approver`, from the teams where they hold reviews.decide (any team for dev); a write whose app
    asks before changes is decided by the person who asked instead, and `for_chat` (their "Allow for this chat")
    stops later writes of that app in the chat from asking. Records the decision,
    then resumes the thread with it. See the module docstring for the retry contract. A publish request's id is decided
    under the publish rules instead (publish_reviews.decide).

    A step that offers `options` (a levy case: hold, flag) is decided by one of them: the decision is recorded as
    approved with the option beside it, `inputs` (validated against the option's declaration) complete its call, and
    the token is minted for that call alone. `amount` is the console's shorthand for the one input so named."""
    if publish_reviews.is_request_id(thread_id):
        return await publish_reviews.decide(rt, approver, thread_id, decision=decision, reason=reason)
    if engine_reviews.is_engine_id(thread_id):
        return await engine_reviews.decide(
            rt,
            approver,
            thread_id,
            decision=decision,
            reason=reason,
            step_up_token=step_up_token,
            inputs=inputs,
            amount=amount,
        )
    from .routers.reviews import record_approval  # noqa: PLC0415 - the router imports this module

    store = graph_store(rt)
    found = await store.thread_row(thread_id)
    if found is None:
        raise NotFound("Review")
    row = found.model_dump()
    _, graph = await resolve(rt, thread_id)
    waiting = pending(await graph.aget_state(config(thread_id)))
    recorded = (await _decisions(rt, [thread_id])).get(thread_id)
    if not waiting or (recorded and recorded.decision_id == waiting[0]["id"]):
        if recorded is None:
            raise Conflict("This thread is not waiting for a decision.", code="run_not_waiting")
        earlier: Json = dict(cast(Json, recorded.review.get("resume") or {}))
        same = recorded.decision == decision or (earlier.get("option") and earlier["option"] == decision)
        if not same:
            was = earlier.get("option") or recorded.decision
            raise Conflict(f"This review was already decided: {was}.", code="already_decided")
        if recorded.resumed_at is None and waiting:
            await _resume(rt, thread_id, recorded)
        return await get_review(rt, thread_id)

    interrupt = waiting[0]
    # The checkpoint's value as it is: held_calls and the decider read it unchecked.
    payload = cast(ThreadPayload, interrupt["payload"])
    try:
        declared = await resolved_options(rt, row, payload)
    except OptionsUnresolved as e:
        raise ValidationFailed(f"This review cannot be decided: {e}") from e
    payload = cast(ThreadPayload, {**payload, "options": declared})
    names = [str(o["name"]) for o in declared]
    if names and decision not in names:
        raise ValidationFailed(f"This review is decided with one of: {', '.join(names)}.")
    if not names and decision not in ("approved", "rejected"):
        raise ValidationFailed("A workflow review is approved or rejected; returning it is not supported.")
    # The call this decision authorises: the option's own, or the step's one call when approved.
    option = decision if names else None
    chosen = next((o for o in declared if o["name"] == option), None)
    call: Json | None = (
        option_call(chosen, inputs, amount)
        if chosen
        else (cast(Json | None, payload.get("call")) if decision == "approved" else None)
    )
    recorded_as = "approved" if option else decision
    # An approval is checked against the call it sends; a rejection against every write the step holds.
    await check_thread_decider(rt, approver, row, payload, [call] if call else held_calls(cast(Json, payload)))
    # Recorded on the decision only once verified: a token sent where none was needed proves nothing.
    verified_step_up: str | None = None
    # The chosen call's policy decides the step-up, not the step's other options (a flag's note asks for none).
    if call and (
        workspace_step_up(approver) or await _needs_step_up(rt, cast(Json, {**payload, "call": call, "options": []}))
    ):
        require_step_up(rt, approver.email, step_up_token)
        verified_step_up = step_up_ref(step_up_token)
    resume: Json = {"decision": recorded_as}
    if option:
        resume["option"] = option
    if reason:
        resume["reason"] = reason
    if step_up_token:
        resume["step_up_token"] = step_up_token
    if for_chat and recorded_as == "approved" and payload.get("ask_first"):
        resume["for_chat"] = True
    if call and option:
        resume["call"] = call
    if call and rt.gateway:
        approval = await record_approval(rt, approver, thread_id, step_up_token, call=call)
        if approval["approvalToken"] is None:
            approvers = cast(JsonValue, approval["approvers"])
            return cast(Json, await get_review(rt, thread_id)) | {"status": "in_review", "approvals": approvers}
        resume["approval_token"] = approval["approvalToken"]
    review = await review_view(rt, row, interrupt, datetime.now(UTC))
    # Recorded before the resume: the decision stands even if the resume fails, and a retry resumes once.
    await ReviewStore(store.engine).record_decision(
        thread_id,
        cast(str, interrupt["id"]),
        decision=recorded_as,
        reason=reason,
        by=approver.email,
        review=cast(Json, review | {"resume": resume}),
        step_up_ref=verified_step_up,
    )
    recorded = (await _decisions(rt, [thread_id]))[thread_id]
    await EventLog(store.engine).append(
        thread_id=thread_id,
        team_id=row["team_id"],
        run_id=None,
        type_="decided",
        data={"decision": recorded_as, "option": option, "decisionId": interrupt["id"], "decidedBy": approver.email},
    )
    await _resume(rt, thread_id, recorded)
    return await get_review(rt, thread_id)


async def check_thread_decider(
    rt: Runtime, approver: Principal, row: Json, payload: ThreadPayload | Json, calls: Sequence[object]
) -> None:
    """Who may decide a paused thread step: a reviewer or admin of the thread's team, whatever the writes it decides
    (`calls`) are, and not who asked for it while requesterMayDecide is off."""
    del calls
    team = str(row["team_id"])
    if payload.get("ask_first"):
        # "Ask the person" is a confirmation: the asker alone answers it, whatever roles they hold and whatever
        # requesterMayDecide says. Nobody else may answer for them.
        require_asker(approver, requester_of(row, payload), what="this")
        return
    require_reviews_decide(review_teams(approver), team, "this review")
    if payload.get("reviewer_role"):
        can(
            caller_of(approver),
            "reviews",
            "decide",
            team=team,
            from_any_team=True,
            role=str(payload.get("reviewer_role")),
            what="this review",
        )
    require_not_own(approver, [requester_of(row, payload)], team=team, what="this")


async def can_decide(rt: Runtime, approver: Principal, review_id: str) -> bool:
    """reviews/decide for the caller on a review waiting now, by the checks its decision route runs."""
    try:
        if publish_reviews.is_request_id(review_id):
            req = await registry(rt).request(review_id)
            await publish_reviews.require_publish_decider(rt, req, approver)
            return req.status == "pending"
        if engine_reviews.is_engine_id(review_id):
            await engine_reviews.check_decider(rt, approver, review_id)
            return True
        found = await graph_store(rt).thread_row(review_id)
        if found is None:
            return False
        row = found.model_dump()
        waiting = pending(await (await resolve(rt, review_id))[1].aget_state(config(review_id)))
        if not waiting:
            return False
        # The checkpoint's value as it is: held_calls and the decider read it unchecked.
        payload = cast(Json, waiting[0]["payload"])
        await check_thread_decider(rt, approver, row, payload, held_calls(payload))
    except ApiError:
        return False
    return True


def option_call(option: Json, inputs: Json | None, amount: float | None) -> Json:
    """The call behind a chosen option, with the reviewer's inputs applied and validated against the option's
    declaration (option_inputs.apply_inputs). `amount` fills the one declared input so named, as the console sends it;
    it is refused when the option declares no such input."""
    given: Json = dict(inputs or {})
    if amount is not None:
        raw_declared: JsonList = list(cast(JsonList, option.get("inputs") or []))
        declared_inputs: list[Json] = [dict(cast(Json, d)) for d in raw_declared]
        named = [str(d["name"]) for d in declared_inputs if str(d["name"]).replace("_", "").casefold() == "amount"]
        if not named:
            raise ValidationFailed(f"The {option.get('name')} option takes no amount.")
        given.setdefault(named[0], float(amount))
    return apply_inputs(option, given)


async def _resume(rt: Runtime, thread_id: str, recorded: DecisionOut) -> None:
    store, leases = graph_store(rt), rt.leases
    assert leases is not None
    attempt = recorded.attempts + 1
    run_id = f"run_{recorded.decision_id[:24]}_{attempt}"
    resume = dict(cast(Json, recorded.review["resume"]))
    try:
        generation = await leases.acquire(thread_id, run_id)
    except LeaseHeldError as e:
        raise Conflict(
            "A run is active on this thread; the decision is recorded and resumes after it.", code="run_active"
        ) from e
    reviews = ReviewStore(store.engine)
    await reviews.update_decision(thread_id, recorded.decision_id, attempts=attempt, run_id=run_id)
    if not await store.start_run(run_id, thread_id, "resume", now_iso(), {"resume": resume}, generation=generation):
        await leases.release(thread_id, run_id)
        raise Conflict("That resume is already running.", code="run_active")
    await store.set_thread_status(thread_id, "busy", now_iso(), generation=generation)
    row, graph = await resolve(rt, thread_id)
    status = "error"
    async for e in execute(rt, row, graph, graph_input=Command(resume=resume), run_id=run_id, kind="resume"):
        if e["event"] == "end":
            status = cast(Json, e["data"])["status"]
    if status in ("done", "interrupted"):
        await reviews.update_decision(thread_id, recorded.decision_id, resumed_at=now_iso())
