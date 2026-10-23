"""Chat routes, exactly as the console's HTTP client calls them (apps/console/src/lib/api/chat-http.ts).

A facade over the graph path (chat_threads.py): a conversation is a thread on the agent wrapper graph, a message
is a leased run on it, and an approval is decided through Reviews. Every JSON route answers in the console's
envelope; POST .../messages streams one `data: <ChatStreamEvent>` frame per event with no envelope.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated, Any, TypeAlias, cast

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import TypeAdapter
from sse_starlette import EventSourceResponse

from ops_access import can
from ops_access.check import DEFAULT as ACCESS
from ops_agents.activities import attachments
from ops_agents.activities.catalog import AgentDefinition
from ops_agents.activities.overrides import limits_for, parse
from ops_agents.activities.overrides import resolve as resolve_settings
from ops_contracts.chat import (
    ApprovalWidget,
    ApproveAction,
    BulkDeleteInput,
    BulkResult,
    BulkSkip,
    BulkUpdateInput,
    ChatAgent,
    ChatMessage,
    ChatOverrides,
    ChatStreamEvent,
    ChatThreadInput,
    ChatThreadPatch,
    DoneEvent,
    ErrorEvent,
    FeedbackInput,
    KbRef,
    PaginationMeta,
    RejectAction,
    SendInput,
    StartEvent,
    TeamDefaultAgent,
    TeamDefaultAgentInput,
    ThreadList,
    WidgetAction,
)
from ops_service_kit.errors import (
    ApiError,
    Conflict,
    Forbidden,
    NotFound,
    Unprocessable,
    ValidationFailed,
)
from ops_service_kit.http import Envelope
from ops_service_kit.ids import new_id, now_iso

from ...store.chat_attachments import ChatAttachments
from ...store.events import EventLog
from ...store.leases import LeaseHeldError
from ...store.team_defaults import TeamDefaults
from .. import hitl_facade
from ..agent_calls import agent_team
from ..agent_registry import definition_of, pinned_definition, refuse_new_turns, registry
from ..auth import Principal, caller_of, principal, require_chat_use
from ..chat_budget import ensure_budget
from ..chat_threads import (
    CHAT_GRAPH,
    NEW_TITLE,
    AssistantBuilder,
    assistant_id,
    chat_row,
    chat_rows,
    matching_ids,
    messages_of,
    store_summary,
    thread_row_view,
    thread_view,
    update_meta,
    with_summaries,
)
from ..child_runs import acting_for
from ..deps import Runtime, runtime
from ..envelope import ok
from ..memory import extract_memories, extractor_for, save_memories
from ..ops_tools import ensure_ops_assistant, fill_cards
from ..runs import config, execute, graph_store, pending, require_graphs, resolve
from .agents import changeable

router = APIRouter(prefix="/chat", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

_ACTION = TypeAdapter[ApproveAction | RejectAction | Any](WidgetAction)


class ServiceUnavailable(ApiError):
    status = 503
    code = "model_unavailable"


async def _thread_row(rt: Runtime, me: Principal | None, thread_id: str) -> dict[str, Any]:
    row = await chat_row(rt, thread_id, me)
    if row is None:
        raise NotFound("Conversation")
    return row


def _meta(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row["meta"])


def _allowed_kbs(rt: Runtime, agent: AgentDefinition) -> list[str]:
    """The bases a thread may choose from: the agent's limits, the same list the override resolver checks, so the
    chips and the settings panel never disagree (limits_for falls back to the agent's default bases)."""
    return limits_for(agent, rt.settings.model_alias).allowed_knowledge_base_ids


async def _check_kbs(rt: Runtime, agent: AgentDefinition, kb_ids: list[str]) -> list[str]:
    """A thread may narrow the agent's knowledge bases, never widen them (spec 07 CD-8). Returns their names, kept on
    the thread so its list and page name them without asking kb-service again. An agent and thread with no knowledge
    need no knowledge service, so a stack without one serves them."""
    if not kb_ids and not agent.default_kb_ids:
        return []
    allowed = _allowed_kbs(rt, agent)
    names = {k.id: k.name for k in await rt.kbs().bases()}
    unknown = [k for k in kb_ids if k not in names]
    if unknown:
        raise Unprocessable(f"Knowledge base {unknown[0]} does not exist or you cannot read it.")
    outside = [k for k in kb_ids if k not in allowed]
    if outside:
        raise Unprocessable(f"{agent.name} cannot search {names[outside[0]]}.")
    return [names[k] for k in kb_ids]


def _state(meta: dict[str, Any]) -> str:
    return "archived" if meta.get("archived") else "pinned" if meta.get("pinned") else "active"


# ── agents ──


@router.get("/agents")
async def agents(rt: Rt) -> JSONResponse:
    """The live agents the caller's team may chat with: the catalogue serves every team's, so it is narrowed to the
    agents the team reads (c-407), and another team's agent is not offered."""
    ours = {r["id"] for r in await registry(rt).rows()}
    try:
        names = {k.id: k.name for k in await rt.kbs().bases()}
    except ApiError:
        # The agent picker still opens when kb-service is down; knowledge bases show by id.
        names = {}
    return ok(
        [
            ChatAgent(
                id=a.id,
                name=a.name,
                role=a.role,
                version=a.version,
                model=rt.settings.model_alias,
                default_kb_ids=a.default_kb_ids,
                suggestions=a.suggestions,
                kbs=[KbRef(id=k, name=names.get(k, k)) for k in _allowed_kbs(rt, a)],
            ).wire()
            for a in rt.catalog.agents
            if a.id in ours
        ]
    )


# ── threads ──


def _cursor(order: str, key: str | int, thread_id: str) -> str:
    """A position in one order: the order it was read in is part of the cursor, so it cannot be replayed in another."""
    return base64.urlsafe_b64encode(json.dumps([order, key, thread_id]).encode()).decode()


def _uncursor(cursor: str, order: str, numeric: bool) -> tuple[str | int, str]:
    """The (key, id) a cursor points after, refused with 400 when it is malformed, from another order, or carries a key
    of the wrong type for this order (which would otherwise fail the comparison as a 500)."""
    try:
        made_in, key, thread_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, TypeError) as e:
        raise ValidationFailed("That cursor is not one this list returned.") from e
    if made_in != order:
        raise ValidationFailed("That cursor belongs to another sort order; start again from the first page.")
    fits = isinstance(key, int) and not isinstance(key, bool) if numeric else isinstance(key, str)
    if not fits or not isinstance(thread_id, str):
        raise ValidationFailed("That cursor is not one this list returned.")
    return key, thread_id


@router.get("/threads")
async def list_threads(
    *,
    request: Request,
    rt: Rt,
    me: Me,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
    search: str | None = None,
    sort_by: Annotated[str | None, Query(alias="sortBy")] = None,
    sort_order: Annotated[str | None, Query(alias="sortOrder")] = None,
    cursor: str | None = None,
    test: bool = False,
) -> JSONResponse:
    """Search runs in SQL over titles, agents, last replies and every question asked; filters, facets and order read
    each thread's meta; only the rows returned are rebuilt from their events. `cursor` pages by position in the order,
    so a thread added or answered meanwhile neither repeats nor skips a row; `page` serves the conversations table.
    Either read returns `nextCursor` while more rows follow."""
    rows = await chat_rows(rt, me)
    await with_summaries(rt, rows)
    # A builder's tests (c-284) are their own list: the conversations, their facets and counts leave them out.
    metas = [(r, m) for r in rows if bool((m := _meta(r)).get("test")) == test]

    facet_keys = ("agentId", "kbIds", "state")
    facets: dict[str, dict[str, int]] = {k: {} for k in facet_keys}

    def values(meta: dict[str, Any], key: str) -> list[str]:
        if key == "agentId":
            return [str(meta.get("agentId"))]
        if key == "kbIds":
            return [str(k) for k in cast(list[Any], meta.get("kbIds") or [])]
        return [_state(meta)]

    for _, m in metas:
        for k in facet_keys:
            for v in values(m, k):
                facets[k][v] = facets[k].get(v, 0) + 1

    found = await matching_ids(rt, search) if search and search.strip() else None
    filters = {k: request.query_params.getlist(k) for k in facet_keys if request.query_params.getlist(k)}
    selected = [
        (r, m)
        for r, m in metas
        if all(set(values(m, k)) & set(want) for k, want in filters.items()) and (found is None or r["id"] in found)
    ]

    def key_of(r: dict[str, Any], m: dict[str, Any]) -> str | int:
        match sort_by:
            case "title":
                return str(m.get("title") or "").lower()
            case "createdAt":
                return str(r["created_at"])
            case "messageCount":
                return int(m.get("messageCount") or 0)
            case _:
                return str(m.get("lastMessageAt") or r["created_at"])

    descending = (sort_order or ("asc" if sort_by == "title" else "desc")) == "desc"
    order = f"{sort_by or 'lastMessageAt'}:{'desc' if descending else 'asc'}"
    ordered = sorted(((key_of(r, m), str(r["id"]), r) for r, m in selected), key=lambda x: x[:2], reverse=descending)
    total = len(ordered)
    if cursor is not None:
        after = _uncursor(cursor, order, numeric=sort_by == "messageCount")
        rest = [x for x in ordered if (x[:2] < after if descending else x[:2] > after)]
        chosen, more = rest[:page_size], len(rest) > page_size
        start = total - len(rest)
    else:
        start = (page - 1) * page_size
        chosen, more = ordered[start : start + page_size], start + page_size < total
    next_cursor = _cursor(order, *chosen[-1][:2]) if more and chosen else None
    page_rows = [x[2] for x in chosen]
    msgs = await messages_of(rt, [r["id"] for r in page_rows])
    result = ThreadList(
        data=[thread_row_view(rt, r, msgs[r["id"]]) for r in page_rows],
        pagination=PaginationMeta(
            page=page if cursor is None else start // page_size + 1,
            page_size=page_size,
            total=total,
            total_pages=max(1, math.ceil(total / page_size)),
            has_next=more,
            has_prev=start > 0,
        ),
        facets=facets,
        next_cursor=next_cursor,
    )
    return ok(result.wire())


@router.get("/default-agent", response_model=Envelope[TeamDefaultAgent])
async def get_default_agent(rt: Rt, me: Me) -> JSONResponse:
    """The agent the caller's team starts chats on (c-174); its name is absent when that agent is no longer live."""
    agent_id = await TeamDefaults(rt.db).agent(me.team_id)
    agent = rt.catalog.agent(agent_id) if agent_id else None
    try:
        can(caller_of(me), "chat", "manage", team=me.team_id, what="the team's default agent")
        may = True
    except Forbidden:
        may = False
    return ok(TeamDefaultAgent(agent_id=agent_id, agent_name=agent.name if agent else None, can_change=may).wire())


@router.put("/default-agent", response_model=Envelope[TeamDefaultAgent])
async def set_default_agent(rt: Rt, me: Me, body: TeamDefaultAgentInput) -> JSONResponse:
    """chat.manage (team admins): the default changes where every member's new chat starts. Provisioning (c-175) sets
    a team's first one through this route; the agent must be live and belong to the team, or to no team."""
    can(caller_of(me), "chat", "manage", team=me.team_id, what="the team's default agent")
    agent = rt.catalog.agent(body.agent_id)
    if agent is None:
        raise Unprocessable("That agent is not live, so new chats cannot start on it.", code="agent_not_live")
    if (team := await agent_team(rt, agent.id)) and team != me.team_id:
        raise Unprocessable(f"{agent.name} belongs to another team.", code="other_team_agent")
    await TeamDefaults(rt.db).set_agent(me.team_id, agent.id, by=me.email)
    return ok(TeamDefaultAgent(agent_id=agent.id, agent_name=agent.name, can_change=True).wire())


async def _team_default(rt: Runtime, me: Principal) -> AgentDefinition:
    """The live default agent of the caller's team, for a chat started without naming one. A team that has set none
    gets its own Ops Assistant on this first chat, set as its default (c-469), so a first chat is never refused; a team
    admin can change the default afterwards."""
    agent_id = await TeamDefaults(rt.db).agent(me.team_id)
    if agent_id is None:
        return await ensure_ops_assistant(rt, me.team_id)
    agent = rt.catalog.agent(agent_id)
    if agent is None:
        why = "default agent is not live"
        raise Conflict(
            f"This team {why}, so pick an agent; a team admin sets the default in General settings.",
            code="no_default_agent",
        )
    return agent


async def _test_agent(rt: Runtime, me: Principal, agent_id: str, version: int | None = None) -> AgentDefinition:
    """The agent a test thread's message runs (c-284): its newest version, draft included, as saved now, never from a
    cache keyed by a version number a draft keeps while it changes; or the saved version the thread was started on, for
    a compare (c-286). Refused unless the caller may test the agent."""
    row = await changeable(rt, me, agent_id, "test")
    n = version if version is not None else int(row["version"])
    try:
        saved = await registry(rt).version(agent_id, n)
    except NotFound:
        raise Unprocessable(f"The agent has no version {n}.", code="unknown_version") from None
    return definition_of(agent_id, n, saved["spec"])


@router.post("/threads")
async def create_thread(rt: Rt, me: Me, body: ChatThreadInput) -> JSONResponse:
    if body.test:
        if body.agent_id is None:
            raise Unprocessable("A test names the agent it tests.")
        agent: AgentDefinition | None = await _test_agent(rt, me, body.agent_id, body.test_version)
    elif body.agent_id is None:
        agent = await _team_default(rt, me)
    else:
        agent = rt.catalog.agent(body.agent_id)
        if agent is None:
            await refuse_new_turns(rt, body.agent_id)
            raise Unprocessable("That agent is not live, so it cannot be chatted with.")
    assert agent is not None
    if not body.test:
        require_chat_use(me, team_id=await agent_team(rt, agent.id))
    # Started on the default without choosing bases, the chat searches the default agent's own.
    kb_ids = body.kb_ids if body.kb_ids or body.agent_id is not None else list(agent.default_kb_ids)
    kb_names = await _check_kbs(rt, agent, kb_ids)
    now = now_iso()
    meta: dict[str, Any] = {
        "chat": True,
        "title": (body.title or "").strip() or NEW_TITLE,
        "agentId": agent.id,
        "agentName": agent.name,
        "agentVersion": agent.version,
        "kbIds": kb_ids,
        "kbNames": kb_names,
        "pinned": False,
        "archived": False,
        "hidden": False,
        "owner": me.name,
        "ownerEmail": me.email,
        "lastMessageAt": now,
        **({"test": True} if body.test else {}),
        **({"testVersion": body.test_version} if body.test and body.test_version else {}),
    }
    if body.attachments:
        meta["attachments"] = [a.model_dump(mode="json", by_alias=True) for a in body.attachments]
    overrides = parse(body.overrides, "thread")
    if overrides is not None:
        # Refused with 422 naming the field before the thread exists, like a settings PATCH.
        resolve_settings(
            limits_for(agent, rt.settings.model_alias),
            agent.default_kb_ids,
            thread=overrides,
            widgets_per_turn=agent.widgets_per_turn,
        )
    thread_id = new_id("th")
    await graph_store(rt).create_thread(thread_id, CHAT_GRAPH, meta, me.team_id, now)
    await ensure_budget(rt, thread_id, agent)
    if overrides is not None and (stored := overrides.model_dump(mode="json", by_alias=True, exclude_none=True)):
        await graph_store(rt).set_overrides(thread_id, stored, updated_at=now)
    await store_summary(rt, thread_id)
    return ok(thread_view(rt, await _thread_row(rt, me, thread_id), []).wire(), status=201)


@router.get("/threads/{thread_id}")
async def get_thread(rt: Rt, me: Me, thread_id: str) -> JSONResponse:
    row = await _thread_row(rt, me, thread_id)
    # Text a guardrail kept or took back from the person is shown to whoever the roles grid lets view the audit.
    audit = ACCESS.may(caller_of(me), "audit", "view", team=me.team_id)
    messages = (await messages_of(rt, [thread_id], audit=audit))[thread_id]
    # An open approval says whether the reader may decide it, so the card offers Approve and Reject only then.
    for w in (w for m in messages for w in m.widgets or [] if isinstance(w, ApprovalWidget)):
        if w.state in ("pending", "awaiting_second"):
            w.can_decide = await hitl_facade.can_decide(rt, me, thread_id)
    # Ops cards are drawn from their records as this reader sees them now (c-469).
    await fill_cards(rt, me, messages)
    return ok(thread_view(rt, row, messages).wire())


@router.patch("/threads/{thread_id}")
async def update_thread(rt: Rt, me: Me, thread_id: str, body: ChatThreadPatch) -> JSONResponse:
    row = await _thread_row(rt, me, thread_id)
    meta = _meta(row)
    patch: dict[str, Any] = {}
    if body.title is not None:
        if not body.title.strip():
            raise ValidationFailed("A conversation needs a title.")
        patch["title"] = body.title.strip()
    if body.pinned is not None:
        patch["pinned"] = body.pinned
    if body.archived is not None:
        patch["archived"] = body.archived
    if body.kb_ids is not None:
        agent = rt.catalog.agent(str(meta.get("agentId")))
        if agent is None:
            raise Unprocessable("This conversation's agent is no longer live.")
        patch["kbNames"] = await _check_kbs(rt, agent, body.kb_ids)
        patch["kbIds"] = body.kb_ids
    if body.agent_id is not None and body.agent_id != meta.get("agentId"):
        patch |= await _handover(rt, me, meta, body.agent_id)
    if patch:
        await update_meta(rt, thread_id, **patch)
        if "title" in patch:
            await store_summary(rt, thread_id)  # a renamed thread is found by its new title
    return await get_thread(rt, me, thread_id)


async def _handover(rt: Runtime, me: Principal, meta: dict[str, Any], agent_id: str) -> dict[str, Any]:
    """The meta for handing the conversation to `agent_id` (an @mention), checked as starting a chat with it. The agent
    it started on, and that agent's bases, are kept so handing back to it restores them."""
    if meta.get("deploymentId"):
        raise Unprocessable("A conversation on an embedded page stays on its agent.", code="handover_not_allowed")
    agent = rt.catalog.agent(agent_id)
    if agent is None:
        raise Unprocessable("That agent is not live, so the conversation cannot move to it.", code="agent_not_live")
    require_chat_use(me, team_id=await agent_team(rt, agent.id))
    start = {
        "id": meta.get("startAgentId") or meta.get("agentId"),
        "name": meta.get("startAgentName") or meta.get("agentName"),
        "kbIds": meta["startKbIds"] if meta.get("startAgentId") else meta.get("kbIds"),
        "kbNames": meta["startKbNames"] if meta.get("startAgentId") else meta.get("kbNames"),
    }
    moved = {"agentId": agent.id, "agentName": agent.name, "agentVersion": agent.version}
    if agent.id == start["id"]:
        # Back: the start agent and the bases the conversation had before the handover.
        return moved | {
            "kbIds": start["kbIds"] or [],
            "kbNames": start["kbNames"] or [],
            "startAgentId": None,
            "startAgentName": None,
            "startKbIds": None,
            "startKbNames": None,
        }
    kb_ids = list(agent.default_kb_ids)
    return moved | {
        "kbIds": kb_ids,
        "kbNames": await _check_kbs(rt, agent, kb_ids),
        "startAgentId": start["id"],
        "startAgentName": start["name"],
        "startKbIds": start["kbIds"] or [],
        "startKbNames": start["kbNames"] or [],
    }


@router.delete("/threads/{thread_id}")
async def delete_thread(rt: Rt, me: Me, thread_id: str) -> Response:
    await _thread_row(rt, me, thread_id)
    await update_meta(rt, thread_id, hidden=True)
    return ok(None)


@router.post("/threads/bulk-update")
async def bulk_update(rt: Rt, me: Me, body: BulkUpdateInput) -> JSONResponse:
    result = BulkResult(updated=[], skipped=[])
    patch = body.patch
    for tid in body.ids:
        row = await chat_row(rt, tid, me)
        meta = _meta(row) if row else {}
        reason: str | None = None
        if row is None:
            reason = "Not found"
        elif patch.pinned is not None and bool(meta.get("pinned")) == patch.pinned and patch.archived is None:
            reason = "Already pinned" if patch.pinned else "Not pinned"
        elif patch.archived is not None and bool(meta.get("archived")) == patch.archived:
            reason = "Already archived" if patch.archived else "Not archived"
        if reason:
            result.skipped.append(BulkSkip(id=tid, reason=reason))
            continue
        values = patch.model_dump(exclude_none=True)
        if patch.archived:
            values["pinned"] = False
        await update_meta(rt, tid, **values)
        result.updated.append(tid)
    return ok(result.wire())


@router.post("/threads/bulk-delete")
async def bulk_delete(rt: Rt, me: Me, body: BulkDeleteInput) -> JSONResponse:
    result = BulkResult(updated=[], skipped=[])
    for tid in body.ids:
        row = await chat_row(rt, tid, me)
        if row is None:
            result.skipped.append(BulkSkip(id=tid, reason="Not found"))
        else:
            await update_meta(rt, tid, hidden=True)
            result.updated.append(tid)
    return ok(result.wire())


# ── turns: each message is a run of the agent wrapper graph on the thread ──


def _frame(event: ChatStreamEvent) -> dict[str, str]:
    return {"data": json.dumps(event.wire(), ensure_ascii=False)}


async def _start_run(rt: Runtime, thread_id: str, graph_input: dict[str, Any]) -> tuple[str, dict[str, Any], Any]:
    """Takes the thread's lease and records the run, as POST /v1/threads/{id}/runs/stream does."""
    store = graph_store(rt)
    row, graph = await resolve(rt, thread_id)
    if waiting := pending(await graph.aget_state(config(thread_id))):
        kinds = {cast(dict[str, Any], w["payload"]).get("kind") for w in waiting if isinstance(w["payload"], dict)}
        if "budget_exhausted" in kinds:
            raise Conflict("This conversation is paused on its budget; continue it first.", code="budget_paused")
        raise Conflict("This conversation is waiting for an approval; decide it first.", code="run_waiting")
    run_id = new_id("run")
    require_graphs(rt)
    assert rt.leases is not None
    try:
        generation = await rt.leases.acquire(thread_id, run_id)
    except LeaseHeldError as e:
        raise Conflict("A reply is already being written in this conversation.", code="run_active") from e
    if not await store.start_run(run_id, thread_id, "input", now_iso(), {"input": graph_input}, generation=generation):
        await rt.leases.release(thread_id, run_id)
        raise Conflict("That run id is already in use.", code="run_active")
    await store.set_thread_status(thread_id, "busy", now_iso(), generation=generation)
    return run_id, row, graph


@router.post("/threads/{thread_id}/messages", response_model=None)
async def send(rt: Rt, me: Me, thread_id: str, body: SendInput) -> EventSourceResponse:
    row = await _thread_row(rt, me, thread_id)
    meta = _meta(row)
    if not body.content.strip() and not body.regenerate:
        raise ValidationFailed("Type a message first.")
    if rt.ports is None:
        raise ServiceUnavailable(rt.model_error or "No model is configured.")
    # A widget conversation serves the version its deployment pins (c-117); every other one the live version.
    pinned = meta.get("agentVersion") if meta.get("deploymentId") else None
    test = bool(meta.get("test"))
    tested = (
        await _test_agent(rt, me, str(meta.get("agentId")), cast(int | None, meta.get("testVersion"))) if test else None
    )
    if pinned is not None and rt.catalog.agent(str(meta.get("agentId"))) is None:
        # The pin chooses the version only: a paused or withdrawn agent takes no new turns on a widget conversation.
        await refuse_new_turns(rt, str(meta.get("agentId")))
        raise Unprocessable("This conversation's agent is no longer live.")
    agent = (
        tested
        if test
        else await pinned_definition(rt, str(meta.get("agentId")), int(pinned))
        if pinned is not None
        else rt.catalog.agent(str(meta.get("agentId")))
    )
    if agent is None:
        await refuse_new_turns(rt, str(meta.get("agentId")))
        raise Unprocessable("This conversation's agent is no longer live.")
    # A conversation from before per-conversation caps takes them now (c-103).
    await ensure_budget(rt, thread_id, agent)
    current = (await messages_of(rt, [thread_id]))[thread_id]

    question = body.content.strip()
    user_message: ChatMessage | None = None
    replaced: list[str] = []
    if body.regenerate:
        i = next((n for n, m in enumerate(current) if m.id == body.regenerate), None)
        if i is None:
            raise NotFound("Message")
        prior_user = next((n for n in range(i - 1, -1, -1) if current[n].role == "user"), None)
        if prior_user is None:
            raise Unprocessable("There is no question before that reply to answer again.")
        question = current[prior_user].content
        transcript, replaced = current[:prior_user], [m.id for m in current[i:]]
    else:
        transcript = current
        if body.edit:
            i = next((n for n, m in enumerate(current) if m.id == body.edit), None)
            if i is None:
                raise NotFound("Message")
            transcript, replaced = current[:i], [m.id for m in current[i:]]
        user_message = ChatMessage(
            id=new_id("m"), role="user", content=question, at=now_iso(), attachments=body.attachments or None
        )

    graph_input: dict[str, Any] = {
        "agent_id": agent.id,
        **({"agent_version": agent.version} if pinned is not None else {}),
        **({"test_agent": agent.model_dump(mode="json")} if test else {}),
        "message": question,
        "history": [{"role": m.role, "content": m.content} for m in transcript],
        "requested_by": me.email,
    }
    # The settings this turn runs on: the agent's limits, then the thread's overrides, then this message's; a value
    # outside the limits is a 422 naming the field and no run starts.
    thread_overrides = ChatOverrides.model_validate(row["overrides"]) if row.get("overrides") else None
    turn_overrides = parse(body.overrides, "turn")
    effective = resolve_settings(
        limits_for(agent, rt.settings.model_alias),
        agent.default_kb_ids,
        thread=thread_overrides,
        turn=turn_overrides,
        widgets_per_turn=agent.widgets_per_turn,
    )
    if "knowledgeBaseIds" in effective.sources:
        graph_input["kb_ids"] = effective.knowledge_base_ids
    elif meta.get("kbIds"):
        # The bases picked when the thread was started stay outside the resolver: one the agent has since lost is
        # answered as withdrawn (agent_wrapper._granted), not refused on every message.
        graph_input["kb_ids"] = [str(k) for k in cast(list[Any], meta["kbIds"])]
        effective.knowledge_base_ids = graph_input["kb_ids"]
        effective.sources["knowledgeBaseIds"] = "started"
    graph_input["settings"] = effective.model_dump(mode="json", by_alias=True)
    if user_message is not None:
        graph_input["user_message_id"] = user_message.id
        if user_message.attachments:
            graph_input["attachments"] = [a.model_dump(mode="json", by_alias=True) for a in user_message.attachments]
    # Kept on the run as they were sent, beside the settings resolved from them.
    if row.get("overrides"):
        graph_input["thread_overrides"] = row["overrides"]
    if meta.get("attachments"):
        graph_input["thread_attachments"] = meta["attachments"]
    if turn_overrides is not None:
        graph_input["overrides"] = turn_overrides.model_dump(mode="json", by_alias=True, exclude_none=True)
    # Files attached to this message or earlier in the thread, read from their parsed text and cited like knowledge.
    # A file id the person does not hold in this team is not found, never silently skipped.
    asked_ids = [a.file_id for a in body.attachments or []]
    earlier_ids = [a.file_id for m in transcript if m.role == "user" for a in m.attachments or []]
    held = await ChatAttachments(graph_store(rt).engine).owned(
        list(dict.fromkeys([*asked_ids, *earlier_ids])), owner_email=me.email, team_id=me.team_id
    )
    if missing := [i for i in asked_ids if i not in held]:
        raise NotFound(f"Attachment {missing[0]}")
    cut: list[str] = []
    budget = attachments.TURN_TEXT_CHARS
    attached: list[dict[str, Any]] = []
    for file_id in dict.fromkeys([*asked_ids, *earlier_ids]):
        if (a := held.get(file_id)) is None:
            continue
        pages = [attachments.Page(p.get("page"), str(p.get("section") or ""), str(p["text"])) for p in a["pages"]]
        found, was_cut = attachments.passages(str(a["name"]), file_id, pages, budget)
        budget -= sum(len(p.text) for p in found)
        attached += [
            {"documentId": p.document_id, "title": p.title, "section": p.section, "page": p.page, "text": p.text}
            for p in found
        ]
        if was_cut or a["truncated"]:
            cut.append(str(a["name"]))
    if attached:
        graph_input["attached_passages"] = attached
    run_id, thread_row, graph = await _start_run(rt, thread_id, graph_input)
    if replaced:
        # The supersede rule: the replaced turns stay in the log and drop out of the conversation.
        await EventLog(graph_store(rt).engine).append(
            thread_id=thread_id,
            team_id=row["team_id"],
            run_id=None,
            type_="superseded",
            data={"messageIds": replaced, "byRun": run_id},
        )
    patch: dict[str, Any] = {"lastMessageAt": now_iso()}
    if meta.get("title") == NEW_TITLE:
        patch["title"] = question if len(question) <= 48 else question[:47].rstrip() + "…"
    await update_meta(rt, thread_id, **patch)

    # Every turn's settings, for the audit trail as `run.settings` and on the reply for whoever reads it later.
    await EventLog(graph_store(rt).engine).append(
        thread_id=thread_id, team_id=row["team_id"], run_id=run_id, type_="run.settings", data=effective.wire()
    )
    assistant = ChatMessage(
        id=assistant_id(run_id),
        role="assistant",
        content="",
        at=now_iso(),
        settings=effective,
        agent_id=agent.id,
        agent_name=agent.name,
    )
    builder = AssistantBuilder(rt.catalog, assistant)

    # What the person said about themselves is read while the reply is written: the extraction needs only their
    # message, and run after the reply it held the reply's end back by a whole model call (c-124).
    extraction = (
        asyncio.ensure_future(
            extract_memories(
                extractor_for(rt),
                agent,
                thread_id=thread_id,
                message=question,
            )
        )
        # A test remembers nothing about the builder (c-284).
        if not body.regenerate and agent.memory_enabled and not test
        else None
    )

    async def stream() -> AsyncIterator[dict[str, str]]:
        try:
            async for frame in reply():
                yield frame
        finally:
            if extraction is not None and not extraction.done():
                extraction.cancel()

    async def reply() -> AsyncIterator[dict[str, str]]:
        yield _frame(StartEvent(user_message=user_message, message_id=assistant.id))
        # The turn runs for this person: a workflow tool is offered and started only if they may start it (c-149).
        with acting_for(me):
            async with aclosing(
                execute(rt, thread_row, graph, graph_input=graph_input, run_id=run_id, kind="input")
            ) as run:
                async for e in run:
                    for out in builder.apply_run_event(e):
                        yield _frame(out)
        if cut:
            # Told in the reply, and kept in the log so a reload says the same.
            note = f"\n\n_Only part of {', '.join(cut)} was read; ask about a specific page or section for the rest._"
            await EventLog(graph_store(rt).engine).append(
                thread_id=thread_id, team_id=row["team_id"], run_id=run_id, type_="text", data=note
            )
            for out in builder.apply("text", note):
                yield _frame(out)
        await update_meta(rt, thread_id, lastMessageAt=now_iso())
        await store_summary(rt, thread_id)
        if extraction is not None and not assistant.error:
            # What the person said about themselves is kept for their next chat with this agent (c-124).
            saved = await save_memories(
                rt, me, agent, await extraction, team_id=str(row["team_id"]), thread_id=thread_id, run_id=run_id
            )
            builder.apply("memory", {"saved": saved})
        if assistant.error:
            yield _frame(ErrorEvent(message=assistant.error, partial=assistant, code=assistant.error_code))
        else:
            yield _frame(DoneEvent(message=assistant))

    # `sep="\n"`: the console splits frames on a blank line made of "\n\n", not "\r\n\r\n".
    return EventSourceResponse(stream(), sep="\n", ping=15)


@router.put("/threads/{thread_id}/messages/{message_id}/feedback")
async def feedback(rt: Rt, me: Me, thread_id: str, message_id: str, body: FeedbackInput) -> JSONResponse:
    row = await _thread_row(rt, me, thread_id)
    if not any(m.id == message_id for m in (await messages_of(rt, [thread_id]))[thread_id]):
        raise NotFound("Message")
    fb = body.feedback.model_dump(mode="json", exclude_none=True) if body.feedback else None
    await EventLog(graph_store(rt).engine).append(
        thread_id=thread_id,
        team_id=row["team_id"],
        run_id=None,
        type_="feedback",
        data={"messageId": message_id, "feedback": fb},
    )
    return ok(None)


@router.post("/threads/{thread_id}/messages/{message_id}/widgets/{widget_id}/actions")
async def widget_action(
    *, rt: Rt, me: Me, thread_id: str, message_id: str, widget_id: str, raw: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    """An approval widget's decision goes through Reviews' decide, like every review-owned step: requester check,
    step-up for money, the approval token, then the resume, whose reply is a new assistant message. An approver who is
    not the chat's owner decides here too, so the owner rule is left to the review policy; the team rule holds."""
    await _thread_row(rt, None, thread_id)
    message = next((m for m in (await messages_of(rt, [thread_id]))[thread_id] if m.id == message_id), None)
    widget = next((w for w in (message.widgets or []) if w.id == widget_id), None) if message else None
    if widget is None:
        raise NotFound("Widget")
    action = _ACTION.validate_python(raw)
    if not isinstance(widget, ApprovalWidget):
        raise ValidationFailed("This widget has no actions.")
    if not isinstance(action, ApproveAction | RejectAction):
        raise ValidationFailed("An approval is approved or rejected, not submitted.")
    if widget.state not in ("pending", "awaiting_second"):
        raise Conflict("This approval was already decided.")
    if isinstance(action, RejectAction) and not action.reason.strip():
        raise ValidationFailed("Give a reason for rejecting.")
    if rt.ports is None:
        raise ServiceUnavailable(rt.model_error or "No model is configured.")
    await hitl_facade.decide(
        rt,
        me,
        thread_id,
        decision="approved" if isinstance(action, ApproveAction) else "rejected",
        reason=action.reason.strip() if isinstance(action, RejectAction) else None,
        step_up_token=action.step_up_token if isinstance(action, ApproveAction) else None,
    )
    await update_meta(rt, thread_id, lastMessageAt=now_iso())
    decided = next(m for m in (await messages_of(rt, [thread_id]))[thread_id] if m.id == message_id)
    return ok(next(w for w in decided.widgets or [] if w.id == widget_id).wire())
