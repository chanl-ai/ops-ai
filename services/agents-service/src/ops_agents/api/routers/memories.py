"""A person's memories with each agent (c-124): `/v1/me/memories` lists, corrects, exports and forgets what agents
remember about the caller, and only the caller. There is no route that reads another person's memories: an admin
manages the agent's memory setting, not what it holds about people."""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_access import can
from ops_contracts.chat import WireModel
from ops_service_kit.errors import NotFound, ValidationFailed
from ops_service_kit.http import Envelope

from ...store.memories import Memories
from ..auth import Principal, caller_of, principal
from ..deps import Runtime, runtime
from ..envelope import ok
from ..memory import person_of
from ..runs import graph_store
from ..schemas import MemoryExport, MemoryView

router = APIRouter(prefix="/v1/me/memories", dependencies=[Depends(principal)])

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


class Forgotten(WireModel):
    forgotten: int


class MemoryCorrection(WireModel):
    value: str = Field(min_length=1, max_length=2000)


def require_memory_access(me: Principal, *, owner: str, edit: bool) -> None:
    """ops_access on memories whose subject is `owner`: chat.view to read, memory.edit to correct or forget, a cell of
    its own so a policy can tighten edits without touching chat. Every role holds both for its own memories only; an
    API key, which is no person and has no memories, is refused."""
    area, action = ("memory", "edit") if edit else ("chat", "view")
    can(caller_of(me), area, action, owner=owner, what="your memories", from_any_team=True)


def _store(rt: Runtime, me: Principal, *, edit: bool = False) -> Memories:
    """The caller's own memories, after require_memory_access with the caller as their subject."""
    require_memory_access(me, owner=me.email, edit=edit)
    return Memories(graph_store(rt).engine)


def _view(rt: Runtime, r: dict[str, Any]) -> dict[str, Any]:
    agent = rt.catalog.agent_in_flight(str(r["agent_id"])) or rt.catalog.agent(str(r["agent_id"]))
    return {
        "id": r["id"],
        "agentId": r["agent_id"],
        "agentName": agent.name if agent else r["agent_id"],
        "kind": r["kind"],
        "key": r["key"],
        "value": r["value"],
        "confidence": r["confidence"],
        "source": r["source"],
        "sourceThreadId": r["source_thread_id"],
        "createdAt": r["created_at"],
    }


@router.get("", response_model=Envelope[list[MemoryView]])
async def list_memories(rt: Rt, me: Me, agent_id: Annotated[str | None, Query(alias="agentId")] = None) -> JSONResponse:
    """What agents remember about the caller, newest first; `agentId` keeps one agent's."""
    return ok([_view(rt, r) for r in await _store(rt, me).current(person_of(me), agent_id)])


@router.patch("/{memory_id}", response_model=Envelope[MemoryView])
async def correct_memory(rt: Rt, me: Me, memory_id: str, body: MemoryCorrection) -> JSONResponse:
    """Replaces a memory's value with the caller's own; the old value is kept as superseded and is no longer loaded."""
    store, person = _store(rt, me, edit=True), person_of(me)
    old = await store.get(person, memory_id)
    if old is None or old["superseded_at"]:
        raise NotFound("Memory")
    if not old["key"]:
        await store.supersede(person, memory_id)
    row = await store.save(
        team_id=str(old["team_id"]),
        agent_id=str(old["agent_id"]),
        person=person,
        kind=str(old["kind"]),
        key=old["key"],
        value=body.value.strip(),
        confidence=1.0,
        source="person",
        thread_id=old["source_thread_id"],
    )
    await store.audit(person, "correct", actor=me.email, agent_id=str(old["agent_id"]), memory_id=row["id"])
    return ok(_view(rt, row))


@router.delete("/{memory_id}", status_code=204, response_class=Response)
async def forget_memory(rt: Rt, me: Me, memory_id: str) -> Response:
    """Forgets one memory and its earlier versions at once; recorded with who and when."""
    if not await _store(rt, me, edit=True).forget(person_of(me), actor=me.email, memory_id=memory_id):
        raise NotFound("Memory")
    return Response(status_code=204)


@router.delete("", response_model=Envelope[Forgotten])
async def forget_agent_memories(
    rt: Rt, me: Me, agent_id: Annotated[str | None, Query(alias="agentId")] = None
) -> JSONResponse:
    """Forgets everything one agent remembers about the caller."""
    if not agent_id:
        raise ValidationFailed("Name the agent whose memories to forget (agentId).", code="agent_required")
    return ok({"forgotten": await _store(rt, me, edit=True).forget(person_of(me), actor=me.email, agent_id=agent_id)})


@router.get("/export", response_model=Envelope[MemoryExport])
async def export_memories(rt: Rt, me: Me) -> JSONResponse:
    """Everything agents remember about the caller and every forget and correction, as one JSON document."""
    store, person = _store(rt, me), person_of(me)
    rows = await store.current(person, None, limit=10_000)
    await store.audit(person, "export", actor=me.email, agent_id="*")
    return ok({"person": person, "memories": [_view(rt, r) for r in rows], "audit": await store.audit_rows(person)})
