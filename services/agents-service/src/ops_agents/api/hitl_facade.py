"""Runtime threads as the console's Cases runs and Reviews, on the console's own HTTP contract
(`apps/console/src/lib/api/cases-contract.ts` and the `reviews` area of `contract.ts`).

Every row is built here, joined with its state, journal, SLA timers and decisions, so the console renders what it gets
and never joins two lists. This is the human-in-loop facade until `hitl-service` exists; the routes move there then.

Decide then resume (`docs/architecture/service-map.md`): the decision is recorded first, keyed by the paused step's
interrupt id (the decision id), then the thread is resumed under a run id derived from it. A resume that fails leaves
the decision standing with `resumed_at` unset, and the next decide with the same decision retries the resume once.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from langgraph.types import Command

from ops_service_kit.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger

from ..store.events import EventLog
from ..store.leases import LeaseHeldError
from ..store.reviews import ReviewStore
from ..store.timers import TimerStore
from . import publish_reviews
from .auth import require_step_up
from .deps import Runtime
from .runs import config, execute, graph_store, pending, resolve
from .timers import sla_view
from .tool_access import WritePolicy, policy_of

# Chat agents run on threads too; only workflows are runs on the Cases page.
log = get_logger("ops_agents.api.hitl_facade")
CASE_GRAPHS_EXCLUDED = {"agent_wrapper"}


def is_chat_graph(graph: str) -> bool:
    """Agent graphs: the shared wrapper and the per-agent `agent:<id>` graphs a publish registers. Cases never shows
    them; Reviews lists a chat's write approvals (c-048 T013), decided there or in the conversation."""
    return graph in CASE_GRAPHS_EXCLUDED or graph.startswith("agent:")


STEP_KIND = {
    "human": "review",
    "send_reply": "action",
    "close": "end",
    **dict.fromkeys(["classify", "extract", "draft", "grade", "answer"], "agent"),
}


def _title(graph: str) -> str:
    return graph.replace("_", " ").capitalize()


def _get(d: Any, key: str) -> Any:
    """`d[key]` for a JSON object from the journal or an interrupt, None for anything else."""
    return cast(dict[str, Any], d).get(key) if isinstance(d, dict) else None


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def _minutes_until(ts: str | None, now: datetime) -> int | None:
    due = _parse(ts)
    return None if due is None else int((due - now).total_seconds() // 60)


def _sla_due(sla: dict[str, Any] | None) -> str | None:
    """The open breach deadline, else the open timeout: the time the SLA lapses."""
    open_timers = [t for t in (sla or {}).get("timers", []) if t["state"] == "open"]
    for kind in ("breach", "timeout"):
        due = sorted(t["dueAt"] for t in open_timers if t["kind"] == kind and t["dueAt"])
        if due:
            return due[0]
    return None


def _steps(runs: list[dict[str, Any]], waiting_at: list[str]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {"nodeId": "trigger", "label": "Started", "kind": "trigger", "status": "done", "durationMs": 0}
    ]
    for r in runs:
        if r["kind"] == "sla":
            continue
        open_steps: dict[str, list[dict[str, Any]]] = {}
        for e in r["events"]:
            node = e.get("node")
            if e.get("event") == "node_start" and node:
                step = {"nodeId": node, "label": _title(node), "kind": STEP_KIND.get(node, "tool"), "status": "done"}
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


async def _decisions(rt: Runtime, thread_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Latest decision per thread."""
    return await ReviewStore(graph_store(rt).engine).latest_decisions(thread_ids)


def requester_of(row: dict[str, Any], payload: dict[str, Any]) -> str:
    """Who asked for the paused step: the person recorded on the interrupt when there is one, else the workflow
    itself (the process principal), which no person can be."""
    return str(payload.get("requested_by") or f"workflow:{row['graph']}")


CHAT_GRAPH = "agent_wrapper"


def require_approver_team(policy: WritePolicy, approver_teams: list[str] | None, tool: str) -> None:
    """Refuses an approver outside the operation's approving team; `approver_teams` None (dev) approves for any."""
    if approver_teams is not None and policy.approver_team and policy.approver_team not in approver_teams:
        raise Forbidden(f"Only someone on {policy.approver_team} approves {tool}.")


def _is_chat(row: dict[str, Any]) -> bool:
    """A chat thread (POST /chat/threads): its id is the conversation's, and its meta names the agent."""
    meta: dict[str, Any] = row.get("meta") or {}
    return bool(meta.get("chat"))


async def is_own_request(rt: Runtime, row: dict[str, Any], approver: str, payload: dict[str, Any]) -> bool:
    """True when `approver` asked for the paused step and policy forbids deciding your own. Outside dev nobody decides
    their own. In dev a chat thread's asker may, when the operation's policy allows it (`selfApproval`) or
    `allow_self_approval_in_chat` is on; a workflow's requester never can."""
    if approver != requester_of(row, payload):
        return False
    if row["graph"] != CHAT_GRAPH or rt.settings.environment != "dev":
        return True
    if rt.settings.allow_self_approval_in_chat:
        return False
    tool = _get(payload.get("call"), "tool")
    return not (tool and (await policy_of(rt, str(tool))).self_approval)


async def _needs_step_up(rt: Runtime, payload: dict[str, Any]) -> bool:
    """Approving needs a step-up when the operation is approved by two people."""
    tool = _get(payload.get("call"), "tool")
    return bool(payload.get("step_up")) or bool(tool and (await policy_of(rt, str(tool))).approvers > 1)


async def run_row(
    rt: Runtime, summary: dict[str, Any], decision: dict[str, Any] | None, now: datetime
) -> dict[str, Any]:
    """One thread as a Cases RunRow (`RunRow` in apps/console/src/lib/types/cases.ts). State, status, subject, queue
    and SLA come from its summary row (`summary_rows`), as the list's do; this adds what only the checkpoint and the
    journal hold: the steps, the waiting call, the error and the trigger."""
    row: dict[str, Any] = summary["thread"]
    store = graph_store(rt)
    _, graph = await resolve(rt, row["id"])
    snap = await graph.aget_state(config(row["id"]))
    waiting = summary["state"] == "waiting"
    interrupts = pending(snap)
    work = [r for r in await store.runs(row["id"]) if r["kind"] != "sla"]
    values: dict[str, Any] = snap.values or {}
    email: dict[str, Any] = values.get("email") or {}
    last = work[-1] if work else None
    error = next(
        (e.get("data", {}).get("message") for e in (last or {}).get("events", []) if e["event"] == "error"), None
    )
    payload: dict[str, Any] = interrupts[0]["payload"] if waiting and interrupts else {}
    approved = 1 if decision and decision["decision"] == "approved" and decision["resumed_at"] else 0
    return {
        "id": row["id"],
        "workflowId": row["graph"],
        "workflowName": row["meta"].get("workflowName") or _title(row["graph"]),
        "version": row["version"] or 1,
        "subject": summary["subject"],
        "status": summary["status"],
        "startedAt": summary["startedAt"],
        "durationMs": summary["durationMs"],
        **({"reviewId": row["id"]} if waiting else {}),
        **({"error": error} if summary["state"] == "failed" and error else {}),
        **_trigger(row["meta"] or {}, email),
        "steps": _steps(work, list(snap.next)),
        "state": summary["state"],
        "waitingOn": "Reviewers" if waiting else None,
        "queue": summary["queue"],
        "assignee": None,
        "slaDueAt": summary["slaDueAt"],
        "slaMinutes": summary["slaMinutes"],
        "actionsApproved": approved,
        "actionsPending": 1 if payload.get("call") else 0,
        "caseId": None,
    }


def _trigger(meta: dict[str, Any], email: dict[str, Any]) -> dict[str, str]:
    """What started the run when it was not its own trigger: an agent calling the workflow as a tool."""
    if meta.get("startedBy") == "agent":
        return {"trigger": f"Started by agent {meta.get('agentName') or ''}".rstrip()}
    return {"trigger": f"From {email['sender']}"} if email.get("sender") else {}


def _done_today(r: dict[str, Any], now: datetime) -> bool:
    if r["state"] not in ("done", "failed"):
        return False
    started = _parse(r["startedAt"])
    finished = started.timestamp() + r["durationMs"] / 1000 if started else 0
    return datetime.fromtimestamp(finished, UTC).date() == now.date()


RUN_VIEWS: dict[str, Callable[[dict[str, Any], datetime], bool]] = {
    "needs_person": lambda r, now: r["state"] == "waiting",
    "open": lambda r, now: r["state"] in {"running", "waiting"},
    "past_sla": lambda r, now: r["state"] in ("running", "waiting") and (r["slaMinutes"] or 0) < 0,
    "done_today": _done_today,
}


def _facets(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {c: {} for c in columns}
    for r in rows:
        for c in columns:
            if r.get(c) is not None:
                out[c][str(r[c])] = out[c].get(str(r[c]), 0) + 1
    return out


def page(rows: list[dict[str, Any]], page_no: int, size: int) -> dict[str, Any]:
    total = len(rows)
    pages = max(1, -(-total // size))
    start = (page_no - 1) * size
    meta = {"page": page_no, "pageSize": size, "total": total, "totalPages": pages}
    meta |= {"hasNext": page_no < pages, "hasPrev": page_no > 1}
    return {"data": rows[start : start + size], "pagination": meta}


async def _resolvable(rt: Runtime) -> set[str]:
    """Graph names a thread can run on: the compiled graphs and every published definition."""
    assert rt.graph_store is not None
    return set(await rt.graph_store.latest_versions()) | set(rt.graphs)


async def summary_rows(rt: Runtime, now: datetime, only: str | None = None) -> list[dict[str, Any]]:
    """Every case thread (or `only` that one) as the fields the Cases views, counts, search and facets read, from
    three queries in all. These are the only source of a row's state, status, subject, queue and SLA: the list and
    the detail page both take them from here, so they cannot disagree. Building full rows (`run_row`: checkpoint,
    journal, timers per thread) for every thread made the list cost seconds with a thousand threads; `list_runs`
    builds them for the page only."""
    resolvable = await _resolvable(rt)
    threads = [
        t
        for t in await graph_store(rt).threads(None)
        if not is_chat_graph(t["graph"]) and t["graph"] in resolvable and (only is None or t["id"] == only)
    ]
    runs = await graph_store(rt).run_summaries(only)
    # A thread whose last run failed may still be paused (a failed resume leaves the interrupt in place); its
    # checkpoint says which. Every other status says it directly, so only these few threads are read.
    unsure = [t["id"] for t in threads if t["status"] in ("error", "lease_lost")]
    paused = {t["id"] for t in threads if t["status"] == "interrupted"} | await _still_paused(rt, unsure)
    due = await _open_sla_due(rt, sorted(paused))
    rows: list[dict[str, Any]] = []
    for t in threads:
        work = [r for r in runs.get(t["id"], []) if r["kind"] != "sla"]
        last = work[-1] if work else None
        waiting = t["id"] in paused and t["status"] != "busy"
        failed = t["status"] == "error" or (last is not None and last["status"] == "error")
        state = "running" if t["status"] == "busy" else "waiting" if waiting else "failed" if failed else "done"
        started, finished = _parse(t["created_at"]), _parse(last["finished_at"] if last else None)
        end = now if state in ("running", "waiting") or finished is None else finished
        # The email in the thread's state is the one the latest input run brought.
        email: dict[str, Any] = {}
        for r in reversed(work):
            journal: dict[str, Any] = r["input"] or {}
            given: dict[str, Any] = journal.get("input") or {}
            found_email: dict[str, Any] | None = given.get("email")
            if found_email:
                email = found_email
                break
        sla_due = due.get(t["id"]) if waiting else None
        rows.append(
            {
                "id": t["id"],
                "workflowId": t["graph"],
                "subject": email.get("subject") or t["meta"].get("subject") or _title(t["graph"]),
                "state": state,
                "status": {"running": "running", "waiting": "waiting_review", "failed": "failed", "done": "completed"}[
                    state
                ],
                "startedAt": t["created_at"],
                "durationMs": int((end - started).total_seconds() * 1000) if started else 0,
                "queue": "Reviews" if waiting else None,
                "slaMinutes": _minutes_until(sla_due, now),
                "slaDueAt": sla_due,
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
) -> dict[str, Any]:
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
    decisions = await _decisions(rt, [r["id"] for r in paged["data"]])
    full: list[dict[str, Any]] = []
    for r in paged["data"]:
        try:
            full.append(await run_row(rt, r, decisions.get(r["id"]), now))
        except (NotFound, Conflict) as e:
            # Its graph cannot be compiled (a version removed, a digest changed): leave it out, not the whole list.
            log.warning("case_row_skipped", thread=r["id"], graph=r["workflowId"], error=e.code)
    return {**paged, "data": full, "facets": facets, "viewCounts": counts}


async def get_run(rt: Runtime, thread_id: str) -> dict[str, Any]:
    now = datetime.now(UTC)
    found = await summary_rows(rt, now, only=thread_id)
    if not found:
        raise NotFound("Run")
    return await run_row(rt, found[0], (await _decisions(rt, [thread_id])).get(thread_id), now)


# ── Reviews ──


async def _approvers(rt: Runtime, thread_id: str, step: str) -> list[str]:
    return await ReviewStore(graph_store(rt).engine).approvers(thread_id, step)


async def review_view(rt: Runtime, row: dict[str, Any], interrupt: dict[str, Any], now: datetime) -> dict[str, Any]:
    """A paused review step as a console `Review`; `status` is pending until a decision is recorded."""
    payload: dict[str, Any] = interrupt["payload"]
    call: dict[str, Any] = payload.get("call") or {}
    policy = await policy_of(rt, call["tool"]) if call.get("tool") else None
    access = policy.access if policy else "unknown"
    two = bool(policy and policy.approvers > 1)
    due = _sla_due(await sla_view(rt, row["id"]))
    chat = _is_chat(row)
    agent_name = str(row["meta"].get("agentName") or row["meta"].get("agentId") or "")
    if chat and call.get("tool"):
        title = f"Run {call['tool']} for {agent_name}"
    elif payload.get("to"):
        title = f"Send reply to {payload['to']}"
    else:
        title = f"Review {_title(row['graph'])}"
    origin: dict[str, Any] = (
        {"kind": "chat", "threadId": row["id"], "agentName": agent_name} if chat else {"kind": "workflow"}
    )
    return {
        "origin": origin,
        "id": row["id"],
        "title": title,
        "customer": payload.get("to") or "",
        "workflowId": row["graph"],
        "workflowName": row["meta"].get("workflowName") or _title(row["graph"]),
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
        "slaMinutes": _minutes_until(due, now) or 0,
        "approvals": await _approvers(rt, row["id"], call["step"]) if call.get("step") else [],
        "status": "pending",
        "createdAt": row["updated_at"],
        "reasoning": _reasoning(payload),
        "evidence": [{"kind": "tool", "label": call["tool"], "detail": str(call.get("input") or {})}] if call else [],
        "stepUp": await _needs_step_up(rt, payload),
    }


def _reasoning(payload: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if payload.get("score") is not None:
        out.append(f"The draft was graded {payload['score']}.")
    if payload.get("attempts"):
        out.append(f"Drafted in {payload['attempts']} attempts.")
    return out


def _decided(d: dict[str, Any]) -> dict[str, Any]:
    review: dict[str, Any] = dict(d["review"])
    # A decision recorded before reviews named their origin was a workflow's: chat approvals were not listed then.
    review.setdefault("origin", {"kind": "workflow"})
    return review | {"status": d["decision"], "decidedAt": d["decided_at"], "decisionReason": d["reason"]}


async def all_reviews(rt: Runtime) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    decisions = await _decisions(rt)
    for row in await graph_store(rt).threads(None):
        # A chat's write approval is listed, so a second approver need not be sent a chat link; other agent graph
        # threads take no review here yet.
        if is_chat_graph(row["graph"]) and not _is_chat(row):
            continue
        try:
            _, graph = await resolve(rt, row["id"])
        except (NotFound, Conflict) as e:
            log.warning("review_row_skipped", thread=row["id"], graph=row["graph"], error=e.code)
            continue
        waiting = pending(await graph.aget_state(config(row["id"])))
        d = decisions.get(row["id"])
        if waiting and not (d and d["decision_id"] == waiting[0]["id"]):
            out.append(await review_view(rt, row, waiting[0], now))
        elif d is not None:
            out.append(_decided(d))
    # Agent and workflow publish requests are reviews too: one list, counted and filtered with the rest.
    return out + await publish_reviews.all_views(rt)


def _elapsed_minutes(start: str, end: str) -> float:
    a, b = _parse(start), _parse(end)
    return (b - a).total_seconds() / 60 if a and b else 0.0


REVIEW_VIEWS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "mine": lambda r: False,  # assignment lives in hitl-service; nothing here is assigned to anyone yet
    "open": lambda r: r["status"] in ("pending", "in_review"),
    "overdue": lambda r: r["status"] in ("pending", "in_review") and r["slaMinutes"] < 0,
    "resolved": lambda r: r["status"] in ("approved", "rejected", "returned"),
    "all": lambda r: True,
}


async def list_reviews(
    rt: Runtime, *, view: str, filters: dict[str, list[str]], search: str | None, page_no: int, size: int
) -> dict[str, Any]:
    if view not in REVIEW_VIEWS:
        raise ValidationFailed(f"Unknown view {view}.")
    rows = await all_reviews(rt)
    counts = {name: sum(1 for r in rows if match(r)) for name, match in REVIEW_VIEWS.items() if name != "all"}
    today = datetime.now(UTC).date()
    decided = [r for r in rows if r.get("decidedAt")]
    minutes = sorted(_elapsed_minutes(r["createdAt"], r["decidedAt"]) for r in decided)
    stats = {
        "unassigned": sum(1 for r in rows if REVIEW_VIEWS["open"](r) and not r.get("assignee")),
        "medianDecisionMinutes": round(minutes[len(minutes) // 2]) if minutes else 0,
        "medianDecisionTrendMinutes": 0,
        "approvedAsProposedRate": round(sum(1 for r in decided if r["status"] == "approved") / len(decided), 2)
        if decided
        else 0,
        "decidedToday": sum(1 for r in decided if r["decidedAt"][:10] == today.isoformat()),
    }
    in_view = [r for r in rows if REVIEW_VIEWS[view](r)]
    if search:
        needle = search.lower()
        in_view = [r for r in in_view if needle in r["title"].lower() or needle in r["id"].lower()]
    facets = _facets(in_view, ["risk", "workflowId", "kind", "agentSlug", "status"])
    for column, wanted in filters.items():
        if wanted:
            in_view = [r for r in in_view if str(r.get(column)) in wanted]
    return {**page(in_view, page_no, size), "facets": facets, "viewCounts": counts, "stats": stats}


async def get_review(rt: Runtime, thread_id: str) -> dict[str, Any]:
    """One thread's review, chat-agent threads included: decide serves every review-owned interrupt. A publish
    request's id (AGP-…, WFP-…) answers with that request."""
    if publish_reviews.is_request_id(thread_id):
        return await publish_reviews.get(rt, thread_id)
    row = await graph_store(rt).thread(thread_id)
    if row is None:
        raise NotFound("Review")
    _, graph = await resolve(rt, thread_id)
    waiting = pending(await graph.aget_state(config(thread_id)))
    d = (await _decisions(rt, [thread_id])).get(thread_id)
    if waiting and not (d and d["decision_id"] == waiting[0]["id"]):
        return await review_view(rt, row, waiting[0], datetime.now(UTC))
    if d is not None:
        return _decided(d)
    raise NotFound("Review")


async def decide(
    rt: Runtime,
    approver: str,
    thread_id: str,
    *,
    decision: str,
    reason: str | None,
    step_up_token: str | None,
    approver_teams: list[str] | None = None,
) -> dict[str, Any]:
    """`approver_teams` are the deciding person's teams; None (dev) decides from any team. Records the decision, then
    resumes the thread with it. See the module docstring for the retry contract. A
    publish request's id is decided under the publish rules instead (publish_reviews.decide)."""
    if publish_reviews.is_request_id(thread_id):
        return await publish_reviews.decide(rt, approver, thread_id, decision=decision, reason=reason)
    from .routers.reviews import record_approval  # noqa: PLC0415 - the router imports this module

    if decision not in ("approved", "rejected"):
        raise ValidationFailed("A workflow review is approved or rejected; returning it is not supported.")
    store = graph_store(rt)
    row = await store.thread(thread_id)
    if row is None:
        raise NotFound("Review")
    _, graph = await resolve(rt, thread_id)
    waiting = pending(await graph.aget_state(config(thread_id)))
    recorded = (await _decisions(rt, [thread_id])).get(thread_id)
    if not waiting or (recorded and recorded["decision_id"] == waiting[0]["id"]):
        if recorded is None:
            raise Conflict("This thread is not waiting for a decision.", code="run_not_waiting")
        if recorded["decision"] != decision:
            raise Conflict(f"This review was already {recorded['decision']}.", code="already_decided")
        if recorded["resumed_at"] is None and waiting:
            await _resume(rt, thread_id, recorded)
        return await get_review(rt, thread_id)

    interrupt = waiting[0]
    payload: dict[str, Any] = interrupt["payload"]
    if await is_own_request(rt, row, approver, payload):
        raise Forbidden("You asked for this, so someone else has to decide it.")
    if decision == "approved" and (tool := _get(payload.get("call"), "tool")):
        require_approver_team(await policy_of(rt, str(tool)), approver_teams, str(tool))
    if decision == "approved" and await _needs_step_up(rt, payload):
        require_step_up(rt, approver, step_up_token)
    resume: dict[str, Any] = {"decision": decision}
    if reason:
        resume["reason"] = reason
    if step_up_token:
        resume["step_up_token"] = step_up_token
    if decision == "approved" and rt.gateway and payload.get("call"):
        approval = await record_approval(rt, approver, thread_id, step_up_token, approver_teams=approver_teams)
        if approval["approvalToken"] is None:
            return await get_review(rt, thread_id) | {"status": "in_review", "approvals": approval["approvers"]}
        resume["approval_token"] = approval["approvalToken"]
    review = await review_view(rt, row, interrupt, datetime.now(UTC))
    # Recorded before the resume: the decision stands even if the resume fails, and a retry resumes once.
    await ReviewStore(store.engine).record_decision(
        thread_id, interrupt["id"], decision=decision, reason=reason, by=approver, review=review | {"resume": resume}
    )
    recorded = (await _decisions(rt, [thread_id]))[thread_id]
    await EventLog(store.engine).append(
        thread_id=thread_id,
        team_id=row["team_id"],
        run_id=None,
        type_="decided",
        data={"decision": decision, "decisionId": interrupt["id"], "decidedBy": approver},
    )
    await _resume(rt, thread_id, recorded)
    return await get_review(rt, thread_id)


async def _resume(rt: Runtime, thread_id: str, recorded: dict[str, Any]) -> None:
    store, leases = graph_store(rt), rt.leases
    assert leases is not None
    attempt = recorded["attempts"] + 1
    run_id = f"run_{recorded['decision_id'][:24]}_{attempt}"
    resume = dict(recorded["review"]["resume"])
    try:
        generation = await leases.acquire(thread_id, run_id)
    except LeaseHeldError as e:
        raise Conflict(
            "A run is active on this thread; the decision is recorded and resumes after it.", code="run_active"
        ) from e
    reviews = ReviewStore(store.engine)
    await reviews.update_decision(thread_id, recorded["decision_id"], attempts=attempt, run_id=run_id)
    if not await store.start_run(run_id, thread_id, "resume", now_iso(), {"resume": resume}, generation=generation):
        await leases.release(thread_id, run_id)
        raise Conflict("That resume is already running.", code="run_active")
    await store.set_thread_status(thread_id, "busy", now_iso(), generation=generation)
    row, graph = await resolve(rt, thread_id)
    status = "error"
    async for e in execute(rt, row, graph, graph_input=Command(resume=resume), run_id=run_id, kind="resume"):
        if e["event"] == "end":
            status = e["data"]["status"]
    if status in ("done", "interrupted"):
        await reviews.update_decision(thread_id, recorded["decision_id"], resumed_at=now_iso())
