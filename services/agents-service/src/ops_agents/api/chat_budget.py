"""A chat conversation's budget (c-103): the caps it starts with, and Continue or Raise when they are spent.

Every chat thread gets a thread budget (store/usage.py) from its agent's per-conversation caps when it starts, or on
its next message when it began before caps existed. The thread meter (graphs/metering.py `guard`) pauses the turn on
the interrupt every human step uses when a cap is reached; the chat draws that pause as a budget card
(chat_threads.AssistantBuilder) from the meter's own numbers. Continue, by the thread's owner, adds one more allotment
of what the thread started with; Raise, by an admin of the thread's team, sets new caps for this thread only. Both are
checked here from the caller's token and then resume the paused turn under a resume run, as a review decision does.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

from langgraph.types import Command

from ops_access import can
from ops_agents.activities.catalog import AgentDefinition
from ops_agents.graphs.metering import budget_from
from ops_contracts.chat import BudgetAnswer
from ops_metering import Budget
from ops_service_kit.errors import Conflict, Forbidden, NotFound, Unprocessable
from ops_service_kit.ids import new_id, now_iso

from ..store.events import EventLog
from ..store.leases import LeaseHeldError
from .auth import Principal, caller_of
from .chat_threads import chat_row, owned_by, update_meta
from .deps import Runtime
from .runs import config, execute, graph_store, pending, resolve


def allotment(agent: AgentDefinition) -> dict[str, Any]:
    """What a conversation starts with and what each Continue adds, in the meter's field names."""
    return {"maxCalls": agent.max_conversation_calls, "maxCost": str(agent.max_conversation_cost)}


async def ensure_budget(rt: Runtime, thread_id: str, agent: AgentDefinition) -> None:
    """Gives the thread its starting caps unless it has a budget already; a thread keeps them when its agent changes."""
    if rt.usage is None or await rt.usage.budget(thread_id) is not None:
        return
    allot = allotment(agent)
    await rt.usage.set_budget(thread_id, budget_from(allot))
    await update_meta(rt, thread_id, budgetAllotment=allot)


async def cap_at_agent(rt: Runtime, thread_id: str, agent: AgentDefinition) -> None:
    """A run-API thread's budget the first time its agent is known: the agent's caps, or the caller's budget where it is
    lower (a caller only lowers them; apis.md). Later turns keep whatever the thread has, so a Raise stays raised."""
    if rt.usage is None:
        return
    row = await graph_store(rt).thread(thread_id)
    if row is not None and cast(dict[str, Any], row["meta"] or {}).get("budgetAllotment"):
        return
    allot = allotment(agent)
    limit, given = budget_from(allot), await rt.usage.budget(thread_id)
    if given is not None:
        lower = [x for x in (given.max_calls, limit.max_calls) if x is not None]
        least = [x for x in (given.max_cost, limit.max_cost) if x is not None]
        limit = Budget(
            max_calls=min(lower) if lower else None,
            max_tokens=given.max_tokens,
            max_cost=min(least) if least else None,
        )
    await rt.usage.set_budget(thread_id, limit)
    await update_meta(rt, thread_id, budgetAllotment=allot)


def _budget_pause(snapshot: Any) -> tuple[str, dict[str, Any]] | None:
    """The interrupt id and payload of the budget pause the thread waits on, if any."""
    for p in pending(snapshot):
        payload = cast(dict[str, Any], p["payload"]) if isinstance(p["payload"], dict) else {}
        if payload.get("kind") == "budget_exhausted":
            return str(p["id"]), payload
    return None


def _caps(b: Budget) -> dict[str, Any]:
    return {"maxCalls": b.max_calls, "maxCost": str(b.max_cost) if b.max_cost is not None else None}


def _may(me: Principal, action: str, team: str, *, owner: str | None = None) -> bool:
    """`can(chat, action)` in the thread's team, as a yes or no: `view` with the owner is the grid's own-thread cell,
    `manage` is the admin's (c-149)."""
    try:
        can(caller_of(me), "chat", action, team=team, owner=owner, what="this conversation")
    except Forbidden:
        return False
    return True


def _owner_or_manager(me: Principal, meta: dict[str, Any], team: str) -> bool:
    owner = meta.get("ownerEmail")
    is_owner = _may(me, "view", team, owner=str(owner)) if owner else owned_by(meta, me)
    return is_owner or _may(me, "manage", team)


async def answer(rt: Runtime, me: Principal, thread_id: str, body: BudgetAnswer) -> None:
    """Continues or raises a spent conversation budget and runs the paused turn to its end (or its next pause). The
    thread's lease is taken before the pause is read, so of two answers at once one applies and the other gets 409, and
    nothing is recorded for an answer that does not run."""
    row = await chat_row(rt, thread_id, None)
    if row is None or rt.usage is None:
        raise NotFound("Conversation")
    meta: dict[str, Any] = dict(row["meta"] or {})
    team = str(row["team_id"])
    if body.action == "continue" and not _owner_or_manager(me, meta, team):
        raise Forbidden("Only the person who started this conversation, or an admin, continues it.", code="not_owner")
    if body.action == "raise":
        # chat.manage in the conversation's team: an admin's in the built-in grid.
        can(caller_of(me), "chat", "manage", team=team, what="this conversation's budget", code="admin_only")
    store, leases = graph_store(rt), rt.leases
    assert leases is not None
    run_id = new_id("run")
    try:
        generation = await leases.acquire(thread_id, run_id)
    except LeaseHeldError as e:
        raise Conflict("A reply is already being written in this conversation.", code="run_active") from e
    try:
        new = await _answered_budget(rt, thread_id, meta, body)
        resume = {"decision": "approved", "budget": _caps(new)}
        if not await store.start_run(run_id, thread_id, "resume", now_iso(), {"resume": resume}, generation=generation):
            raise Conflict("That resume is already running.", code="run_active")
    except BaseException:
        await leases.release(thread_id, run_id)
        raise
    # Logged on the run that paused, where the card is drawn, once this answer holds the lease and its run started.
    runs = [
        r for r in await store.runs(thread_id) if r["kind"] in ("input", "resume", "recovery") and r["id"] != run_id
    ]
    await EventLog(store.engine).append(
        thread_id=thread_id,
        team_id=row["team_id"],
        run_id=runs[-1]["id"] if runs else None,
        type_="budget.answered",
        data={"action": body.action, "by": me.email or me.name, "budget": _caps(new)},
    )
    await store.set_thread_status(thread_id, "busy", now_iso(), generation=generation)
    row, graph = await resolve(rt, thread_id)
    async for _ in execute(rt, row, graph, graph_input=Command(resume=resume), run_id=run_id, kind="resume"):
        pass
    await update_meta(rt, thread_id, lastMessageAt=now_iso())


async def _answered_budget(rt: Runtime, thread_id: str, meta: dict[str, Any], body: BudgetAnswer) -> Budget:
    """The caps the conversation goes on with, checked against the pause it waits on now."""
    assert rt.usage is not None
    _, graph = await resolve(rt, thread_id)
    found = _budget_pause(await graph.aget_state(config(thread_id)))
    if found is None:
        raise Conflict("This conversation is not paused on its budget.", code="not_paused")
    pause_id, pause = found
    if body.pause_id is not None and body.pause_id != pause_id:
        raise Conflict("This conversation has moved on; reload it to answer its current pause.", code="stale_pause")
    spent = await rt.usage.totals(thread_id)
    current = await rt.usage.budget(thread_id) or Budget()
    if body.action == "continue":
        allot = budget_from(cast(dict[str, Any], meta.get("budgetAllotment") or {}))
        calls = allot.max_calls or 0
        cost = allot.max_cost or Decimal(0)
        return Budget(
            max_calls=max(current.max_calls or 0, spent.calls) + calls if calls else current.max_calls,
            max_tokens=current.max_tokens,
            max_cost=max(current.max_cost or Decimal(0), spent.cost) + cost if cost else current.max_cost,
        )
    # A raise must lift the cap that paused the turn, or the turn pauses again at once.
    limit = str(pause.get("limit") or "calls")
    if limit == "calls" and body.max_calls is None:
        raise Unprocessable("This conversation paused on model calls; give a new model-call cap.", code="cap_required")
    if limit == "cost" and body.max_cost is None:
        raise Unprocessable("This conversation paused on cost; give a new cost cap.", code="cap_required")
    if limit == "tokens":
        raise Unprocessable(
            "This conversation paused on tokens, which are raised in its agent's limits.", code="cap_required"
        )
    if body.max_calls is not None and body.max_calls <= spent.calls:
        raise Unprocessable(
            f"The conversation has made {spent.calls} model calls; set a cap above that.", code="cap_too_low"
        )
    if body.max_cost is not None and body.max_cost <= spent.cost:
        raise Unprocessable(f"The conversation has spent {spent.cost}; set a cap above that.", code="cap_too_low")
    return current.updated(Budget(max_calls=body.max_calls, max_cost=body.max_cost))


async def run_api_answer(
    rt: Runtime, me: Principal, row: dict[str, Any], pause: dict[str, Any], resume: dict[str, Any]
) -> dict[str, Any]:
    """The resume for a budget pause on a run-API thread (an `agent:` thread, a workflow case), under the chat's rules:
    stopping or continuing is the thread owner's or a team admin's; continuing adds the thread's allotment (its
    agent's caps); a resume that names caps is a raise, a team admin's, above what was spent and lifting the cap that
    paused it. The dev header caller acts as an admin."""
    assert rt.usage is not None
    thread_id, meta = str(row["id"]), cast(dict[str, Any], row["meta"] or {})
    team = str(row["team_id"])
    admin = _may(me, "manage", team)
    owner = bool(meta.get("ownerEmail")) and _may(me, "view", team, owner=str(meta["ownerEmail"]))
    if resume.get("decision") != "approved":
        if not (owner or admin):
            raise Forbidden("Only who started this thread, or an admin of its team, stops it.", code="not_owner")
        return {"decision": resume.get("decision")}
    spent = await rt.usage.totals(thread_id)
    current = await rt.usage.budget(thread_id) or Budget()
    raw = resume.get("budget")
    if raw:
        if not admin:
            raise Forbidden("Only an admin of this thread's team raises its budget.", code="admin_only")
        given = budget_from(cast(dict[str, Any], raw))
        limit = str(pause.get("limit") or "calls")
        lifted = given.max_calls if limit == "calls" else given.max_cost if limit == "cost" else None
        if lifted is None:
            raise Unprocessable(f"This thread paused on {limit}; give a new {limit} cap.", code="cap_required")
        if (given.max_calls is not None and given.max_calls <= spent.calls) or (
            given.max_cost is not None and given.max_cost <= spent.cost
        ):
            raise Unprocessable("Set each cap above what the thread has spent.", code="cap_too_low")
        return {"decision": "approved", "budget": _caps(current.updated(given))}
    if not (owner or admin):
        raise Forbidden("Only who started this thread, or an admin of its team, continues it.", code="not_owner")
    allot = budget_from(cast(dict[str, Any], meta.get("budgetAllotment") or {}))
    if allot.max_calls is None and allot.max_cost is None:
        raise Unprocessable("This thread has no allotment to continue with; an admin raises it.", code="caps_required")
    calls, cost = allot.max_calls or 0, allot.max_cost or Decimal(0)
    new = Budget(
        max_calls=max(current.max_calls or 0, spent.calls) + calls if calls else current.max_calls,
        max_tokens=current.max_tokens,
        max_cost=max(current.max_cost or Decimal(0), spent.cost) + cost if cost else current.max_cost,
    )
    return {"decision": "approved", "budget": _caps(new)}
