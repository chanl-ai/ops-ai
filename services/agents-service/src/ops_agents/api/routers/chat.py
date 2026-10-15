"""Chat routes, exactly as the console's HTTP client calls them (apps/console/src/lib/api/chat-http.ts).

A facade over the graph path (chat_threads.py): a conversation is a thread on the agent wrapper graph, a message
is a leased run on it, and an approval is decided through Reviews. Every JSON route answers in the console's
envelope; POST .../messages streams one `data: <ChatStreamEvent>` frame per event with no envelope.
"""

from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated, Any, TypeAlias, cast

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import TypeAdapter
from sse_starlette import EventSourceResponse

from ops_agents.activities.catalog import AgentDefinition
from ops_contracts.chat import (
    ApprovalWidget,
    ApproveAction,
    BulkDeleteInput,
    BulkResult,
    BulkSkip,
    BulkUpdateInput,
    ChatAgent,
    ChatMessage,
    ChatStreamEvent,
    ChatThreadInput,
    ChatThreadPatch,
    ChatThreadRow,
    DoneEvent,
    ErrorEvent,
    FeedbackInput,
    KbRef,
    PaginationMeta,
    RejectAction,
    SendInput,
    StartEvent,
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
from ops_service_kit.ids import new_id, now_iso

from ...store.events import EventLog
from ...store.leases import LeaseHeldError
from .. import hitl_facade
from ..agent_registry import refuse_new_turns
from ..auth import Principal, principal, teams_of
from ..chat_threads import (
    CHAT_GRAPH,
    NEW_TITLE,
    AssistantBuilder,
    assistant_id,
    chat_row,
    chat_rows,
    messages_of,
    thread_row_view,
    thread_view,
    update_meta,
)
from ..deps import Runtime, runtime
from ..envelope import ok
from ..runs import config, execute, graph_store, pending, resolve

router = APIRouter(prefix="/chat", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

_ACTION = TypeAdapter[ApproveAction | RejectAction | Any](WidgetAction)


class ServiceUnavailable(ApiError):
    status = 503
    code = "model_unavailable"


async def _thread_row(rt: Runtime, thread_id: str) -> dict[str, Any]:
    row = await chat_row(rt, thread_id)
    if row is None:
        raise NotFound("Conversation")
    return row


def _meta(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row["meta"])


def _check_kbs(rt: Runtime, agent: AgentDefinition, kb_ids: list[str]) -> None:
    """A thread may narrow the agent's knowledge bases, never widen them (spec 07 CD-8)."""
    known = {k.id for k in rt.catalog.knowledge_bases}
    unknown = [k for k in kb_ids if k not in known]
    if unknown:
        raise Unprocessable(f"Knowledge base {unknown[0]} does not exist or you cannot read it.")
    outside = [k for k in kb_ids if k not in agent.default_kb_ids]
    if outside:
        raise Unprocessable(f"{agent.name} cannot search {rt.catalog.kb_name(outside[0])}.")


def _state(meta: dict[str, Any]) -> str:
    return "archived" if meta.get("archived") else "pinned" if meta.get("pinned") else "active"


# ── agents ──


@router.get("/agents")
async def agents(rt: Rt) -> JSONResponse:
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
                kbs=[KbRef(id=k, name=rt.catalog.kb_name(k)) for k in a.default_kb_ids],
            ).wire()
            for a in rt.catalog.agents
        ]
    )


# ── threads ──


@router.get("/threads")
async def list_threads(
    *,
    request: Request,
    rt: Rt,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
    search: str | None = None,
    sort_by: Annotated[str | None, Query(alias="sortBy")] = None,
    sort_order: Annotated[str | None, Query(alias="sortOrder")] = None,
) -> JSONResponse:
    rows = await chat_rows(rt)
    msgs = await messages_of(rt, [r["id"] for r in rows])
    built: list[tuple[dict[str, Any], ChatThreadRow]] = [
        (_meta(r), thread_row_view(rt, r, msgs[r["id"]])) for r in rows
    ]

    facet_keys = ("agentId", "kbIds", "state", "owner")
    facets: dict[str, dict[str, int]] = {k: {} for k in facet_keys}

    def values(meta: dict[str, Any], key: str) -> list[str]:
        if key == "agentId":
            return [str(meta.get("agentId"))]
        if key == "kbIds":
            return [str(k) for k in cast(list[Any], meta.get("kbIds") or [])]
        if key == "state":
            return [_state(meta)]
        return [str(meta.get("owner"))]

    for r, _ in built:
        for k in facet_keys:
            for v in values(r, k):
                facets[k][v] = facets[k].get(v, 0) + 1

    filters = {k: request.query_params.getlist(k) for k in facet_keys if request.query_params.getlist(k)}
    selected = [
        (r, row)
        for r, row in built
        if all(set(values(r, k)) & set(want) for k, want in filters.items())
        and (not search or search.lower() in f"{row.title} {row.preview} {row.agent_name}".lower())
    ]
    key = {"title": "title", "createdAt": "created_at", "messageCount": "message_count"}.get(
        sort_by or "", "last_message_at"
    )
    selected.sort(
        key=lambda x: getattr(x[1], key), reverse=(sort_order or ("asc" if key == "title" else "desc")) == "desc"
    )
    total = len(selected)
    start = (page - 1) * page_size
    result = ThreadList(
        data=[row for _, row in selected[start : start + page_size]],
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=max(1, math.ceil(total / page_size)),
            has_next=start + page_size < total,
            has_prev=page > 1,
        ),
        facets=facets,
    )
    return ok(result.wire())


@router.post("/threads")
async def create_thread(rt: Rt, me: Me, body: ChatThreadInput) -> JSONResponse:
    agent = rt.catalog.agent(body.agent_id)
    if agent is None:
        await refuse_new_turns(rt, body.agent_id)
        raise Unprocessable("That agent is not live, so it cannot be chatted with.")
    _check_kbs(rt, agent, body.kb_ids)
    now = now_iso()
    meta = {
        "chat": True,
        "title": (body.title or "").strip() or NEW_TITLE,
        "agentId": agent.id,
        "agentName": agent.name,
        "agentVersion": agent.version,
        "kbIds": body.kb_ids,
        "pinned": False,
        "archived": False,
        "hidden": False,
        "owner": me.name,
        "lastMessageAt": now,
    }
    thread_id = new_id("th")
    await graph_store(rt).create_thread(thread_id, CHAT_GRAPH, meta, me.team_id, now)
    return ok(thread_view(rt, await _thread_row(rt, thread_id), []).wire(), status=201)


@router.get("/threads/{thread_id}")
async def get_thread(rt: Rt, thread_id: str) -> JSONResponse:
    row = await _thread_row(rt, thread_id)
    return ok(thread_view(rt, row, (await messages_of(rt, [thread_id]))[thread_id]).wire())


@router.patch("/threads/{thread_id}")
async def update_thread(rt: Rt, me: Me, thread_id: str, body: ChatThreadPatch) -> JSONResponse:
    row = await _thread_row(rt, thread_id)
    meta = _meta(row)
    if meta.get("owner") != me.name:
        raise Forbidden("Only the owner can change this conversation.")
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
        _check_kbs(rt, agent, body.kb_ids)
        patch["kbIds"] = body.kb_ids
    if patch:
        await update_meta(rt, thread_id, **patch)
    return await get_thread(rt, thread_id)


@router.delete("/threads/{thread_id}")
async def delete_thread(rt: Rt, me: Me, thread_id: str) -> Response:
    row = await _thread_row(rt, thread_id)
    if _meta(row).get("owner") != me.name:
        raise Forbidden("Only the owner can delete this conversation.")
    await update_meta(rt, thread_id, hidden=True)
    return ok(None)


@router.post("/threads/bulk-update")
async def bulk_update(rt: Rt, me: Me, body: BulkUpdateInput) -> JSONResponse:
    result = BulkResult(updated=[], skipped=[])
    patch = body.patch
    for tid in body.ids:
        row = await chat_row(rt, tid)
        meta = _meta(row) if row else {}
        reason: str | None = None
        if row is None:
            reason = "Not found"
        elif meta.get("owner") != me.name:
            reason = "Owned by someone else"
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
        row = await chat_row(rt, tid)
        if row is None:
            result.skipped.append(BulkSkip(id=tid, reason="Not found"))
        elif _meta(row).get("owner") != me.name:
            result.skipped.append(BulkSkip(id=tid, reason="Owned by someone else"))
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
    if pending(await graph.aget_state(config(thread_id))):
        raise Conflict("This conversation is waiting for an approval; decide it first.", code="run_waiting")
    run_id = new_id("run")
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
    row = await _thread_row(rt, thread_id)
    meta = _meta(row)
    if meta.get("owner") != me.name:
        raise Forbidden("Only the owner can continue this conversation.")
    if not body.content.strip() and not body.regenerate:
        raise ValidationFailed("Type a message first.")
    if rt.ports is None:
        raise ServiceUnavailable(rt.model_error or "No model is configured.")
    agent = rt.catalog.agent(str(meta.get("agentId")))
    if agent is None:
        await refuse_new_turns(rt, str(meta.get("agentId")))
        raise Unprocessable("This conversation's agent is no longer live.")
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
        "message": question,
        "kb_ids": list(meta.get("kbIds") or []),
        "history": [{"role": m.role, "content": m.content} for m in transcript],
        "requested_by": me.email,
    }
    if user_message is not None:
        graph_input["user_message_id"] = user_message.id
        if user_message.attachments:
            graph_input["attachments"] = [a.model_dump(mode="json", by_alias=True) for a in user_message.attachments]
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

    assistant = ChatMessage(id=assistant_id(run_id), role="assistant", content="", at=now_iso())
    builder = AssistantBuilder(rt.catalog, assistant)

    async def stream() -> AsyncIterator[dict[str, str]]:
        yield _frame(StartEvent(user_message=user_message, message_id=assistant.id))
        async with aclosing(
            execute(rt, thread_row, graph, graph_input=graph_input, run_id=run_id, kind="input")
        ) as run:
            async for e in run:
                for out in builder.apply_run_event(e):
                    yield _frame(out)
        await update_meta(rt, thread_id, lastMessageAt=now_iso())
        if assistant.error:
            yield _frame(ErrorEvent(message=assistant.error, partial=assistant, code=assistant.error_code))
        else:
            yield _frame(DoneEvent(message=assistant))

    # `sep="\n"`: the console splits frames on a blank line made of "\n\n", not "\r\n\r\n".
    return EventSourceResponse(stream(), sep="\n", ping=15)


@router.put("/threads/{thread_id}/messages/{message_id}/feedback")
async def feedback(rt: Rt, thread_id: str, message_id: str, body: FeedbackInput) -> JSONResponse:
    row = await _thread_row(rt, thread_id)
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
    step-up for money, the approval token, then the resume, whose reply is a new assistant message."""
    await _thread_row(rt, thread_id)
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
        me.email,
        thread_id,
        decision="approved" if isinstance(action, ApproveAction) else "rejected",
        reason=action.reason.strip() if isinstance(action, RejectAction) else None,
        step_up_token=action.step_up_token if isinstance(action, ApproveAction) else None,
        approver_teams=teams_of(me),
    )
    await update_meta(rt, thread_id, lastMessageAt=now_iso())
    decided = next(m for m in (await messages_of(rt, [thread_id]))[thread_id] if m.id == message_id)
    return ok(next(w for w in decided.widgets or [] if w.id == widget_id).wire())
