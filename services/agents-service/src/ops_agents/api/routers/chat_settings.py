"""A chat thread's settings and a chat message's attachments (c-071).

Settings: what the thread's agent lets the banker change, the thread's overrides, and the settings every turn starts
from. PATCH merges into the stored overrides: a field sent replaces that field, a field sent as null clears it, a field
left out is kept, so the panel's four controls never wipe knowledge, budget or widget overrides set elsewhere. The
merged result is checked by the resolver against the agent's limits, so a value outside them, or an unknown field, is
a 422 naming the field and nothing is stored. Owner only, like every chat route.

Attachments: a file's bytes are stored through an ops_storage object store and its text parsed once, here at upload;
type and size are checked first and refused with 422 saying what chat reads. A message names its attachments by id.
"""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from ops_access import can
from ops_agents.activities import attachments
from ops_agents.activities.agent_limits import AgentLimits
from ops_agents.activities.catalog import AgentDefinition
from ops_agents.activities.overrides import limits_for, parse, resolve
from ops_contracts.chat import BudgetAnswer, ChatAttachment, ChatOverrides, NamedRef, ThreadLimits, ThreadSettings
from ops_service_kit.errors import ApiError, NotFound, Unprocessable
from ops_service_kit.ids import now_iso

from ...store.chat_attachments import ChatAttachments
from ..auth import Principal, caller_of, principal
from ..chat_budget import answer as answer_budget
from ..chat_threads import chat_row, messages_of, thread_view
from ..deps import Runtime, runtime
from ..envelope import ok
from ..runs import graph_store

router = APIRouter(prefix="/chat", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


async def _thread(rt: Runtime, me: Principal, thread_id: str) -> tuple[dict[str, Any], AgentDefinition, AgentLimits]:
    row = await chat_row(rt, thread_id, me)
    if row is None:
        raise NotFound("Conversation")
    meta: dict[str, Any] = row["meta"] or {}
    agent = rt.catalog.agent(str(meta.get("agentId")))
    if agent is None:
        raise Unprocessable("This conversation's agent is no longer live.")
    return row, agent, limits_for(agent, rt.settings.model_alias)


async def _view(rt: Runtime, row: dict[str, Any], agent: AgentDefinition, limits: AgentLimits) -> ThreadSettings:
    try:
        kb_names = {k.id: k.name for k in await rt.kbs().bases()}
    except ApiError:
        kb_names = {}  # kb-service down: the panel still opens, bases show by id
    overrides = ChatOverrides.model_validate(row["overrides"]) if row.get("overrides") else None
    return ThreadSettings(
        limits=ThreadLimits(
            allowed_models=limits.allowed_models,
            default_model=limits.default_model,
            temperature_min=limits.temperature.min if limits.temperature else None,
            temperature_max=limits.temperature.max if limits.temperature else None,
            knowledge_bases=[NamedRef(id=k, name=kb_names.get(k, k)) for k in limits.allowed_knowledge_base_ids],
            switchable_tools=[NamedRef(id=t, name=t) for t in limits.switchable_tool_ids],
            may_add_instructions=limits.callers_may_add_instructions,
            budget_ceiling_usd=limits.budget.ceiling_usd if limits.budget else None,
            switchable_widgets=[
                NamedRef(id=w.widget_id, name=w.name)
                for w in agent.widgets
                if w.widget_id in limits.switchable_widget_ids
            ],
            may_compose=agent.compose,
            widgets_per_turn=agent.widgets_per_turn,
        ),
        overrides=overrides,
        effective=resolve(limits, agent.default_kb_ids, thread=overrides, widgets_per_turn=agent.widgets_per_turn),
    )


@router.get("/threads/{thread_id}/settings")
async def get_settings(rt: Rt, me: Me, thread_id: str) -> JSONResponse:
    row, agent, limits = await _thread(rt, me, thread_id)
    return ok((await _view(rt, row, agent, limits)).wire())


def merge(stored: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    """PATCH semantics on wire (camelCase) keys: sent replaces, null clears, absent keeps."""
    merged = {**(stored or {}), **patch}
    return {k: v for k, v in merged.items() if v is not None}


@router.patch("/threads/{thread_id}/settings")
async def patch_settings(rt: Rt, me: Me, thread_id: str, body: Annotated[dict[str, Any], Body()]) -> JSONResponse:
    row, agent, limits = await _thread(rt, me, thread_id)
    merged = parse(merge(row.get("overrides"), body), "thread")
    resolve(
        limits, agent.default_kb_ids, thread=merged, widgets_per_turn=agent.widgets_per_turn
    )  # 422 naming the field, before anything is stored
    stored = (merged.model_dump(mode="json", by_alias=True, exclude_none=True) if merged else None) or None
    await graph_store(rt).set_overrides(thread_id, stored, updated_at=now_iso())
    return ok((await _view(rt, {**row, "overrides": stored}, agent, limits)).wire())


@router.post("/threads/{thread_id}/budget")
async def budget(rt: Rt, me: Me, thread_id: str, body: BudgetAnswer) -> JSONResponse:
    """Continue (the conversation's owner) or raise (an admin of its team) a spent conversation budget; the paused
    turn then runs and the conversation comes back with its reply (c-103). 403 for anyone else, 409 when not paused."""
    await answer_budget(rt, me, thread_id, body)
    row = await chat_row(rt, thread_id, None)
    assert row is not None
    return ok(thread_view(rt, row, (await messages_of(rt, [thread_id]))[thread_id]).wire())


_files: dict[str, attachments.ChatFileStore] = {}


def chat_files(rt: Runtime) -> attachments.ChatFileStore:
    """One store per process, beside kb-service's files under the repo's data folder."""
    root = rt.settings.kb_files_dir.parent / "chat-files"
    return _files.setdefault(str(root), attachments.ChatFileStore.local(root))


@router.post("/attachments", status_code=201)
async def upload_attachment(rt: Rt, me: Me, request: Request, name: str) -> JSONResponse:
    """The file's bytes as the request body, its type as Content-Type. Attaching is part of chatting (chat.run)."""
    can(caller_of(me), "chat", "run", what="this conversation")
    mime = attachments.mime_of(name, request.headers.get("content-type"))
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        # Refused while reading, so an oversized upload is never held whole in memory.
        if len(body) > attachments.MAX_BYTES:
            raise attachments.refuse(f"{name} is larger than {attachments.MAX_BYTES // (1024 * 1024)} MB.")
    if not body:
        raise attachments.refuse(f"{name} is empty.")
    parsed = attachments.read(bytes(body), name=name, mime=mime)
    file_id = chat_files(rt).put(bytes(body), mime=mime, team=me.team_id or "none")
    await ChatAttachments(graph_store(rt).engine).add(
        {
            "id": file_id,
            "team_id": me.team_id,
            "owner_email": me.email,
            "name": name,
            "mime": mime,
            "size": len(body),
            "pages": [{"page": p.page, "section": p.section, "text": p.text} for p in parsed.pages],
            "truncated": parsed.truncated,
            "created_at": now_iso(),
        }
    )
    return ok(ChatAttachment(file_id=file_id, name=name, size=len(body)).wire(), status=201)
