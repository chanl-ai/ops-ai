"""POST /v1/events (c-258): a service reports a named event, and the system workflows that listen to it run. Service
tokens with the `events:emit` scope only; the tenant, team and reporting service come from the token, never the body,
and a service reports only the events the catalogue gives it."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_contracts.chat import WireModel
from ops_engine.node_types import EVENT_NAME
from ops_identity import CurrentService
from ops_service_kit.errors import Forbidden, Unprocessable
from ops_service_kit.http import Envelope

from .. import service_events
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Out

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases

router = APIRouter(prefix="/v1/events")

# The payload becomes a run's input and shows on Activity; a file belongs in Files, referred to by id.
MAX_PAYLOAD_BYTES = 16_384


class EventIn(WireModel):
    name: str = Field(pattern=EVENT_NAME, max_length=120)
    # Unique per occurrence, e.g. the record's id and version: the same key is the same event.
    key: str = Field(min_length=1, max_length=200)
    # The team whose record the event is about; its runs belong to it.
    team_id: str = Field(min_length=1, max_length=64)
    # The person the work is for, when the event is someone's request: the run is theirs.
    actor: str | None = Field(default=None, min_length=3, max_length=320)
    payload: dict[str, Any] = Field(default_factory=dict[str, Any])


class EventOut(Out):
    id: str
    name: str
    key: str
    # started: listener runs began; resumed: a step parked on it carried on (c-525); unhandled: neither.
    status: Literal["started", "resumed", "unhandled"]
    # One run per listening system workflow, the latest attempt of each.
    run_ids: list[str]
    # The waiting runs it resumed: steps parked on this event and key (c-525).
    woke: list[str] = Field(default_factory=list)
    attempts: int


@router.post("", status_code=202, response_model=Envelope[EventOut])
async def emit_event(rt: Rt, caller: CurrentService, body: EventIn) -> JSONResponse:
    """Records the event and starts each listening system workflow's run, or returns the runs a repeat of it started.
    A repeat after a run failed starts the next attempt. 202 whether or not a workflow listens (`unhandled`): the
    reporting service never depends on who reacts."""
    if "events:emit" not in caller.scopes:
        raise Forbidden("This service token does not hold the events:emit scope.", code="scope_required")
    if not caller.tenant_id:
        raise Forbidden("A service event names its workspace in the token.", code="tenant_required")
    if len(json.dumps(body.payload)) > MAX_PAYLOAD_BYTES:
        raise Unprocessable(
            f"An event's payload is at most {MAX_PAYLOAD_BYTES} bytes; refer to a file by its id.",
            code="payload_too_large",
        )
    source = caller.sub.removeprefix("service:")
    if not service_events.owns(source, body.name):
        raise Forbidden(f"{source} does not report {body.name}; another service owns it.", code="event_not_owned")
    # The team is the one the reporting service minted its token for, about its own record; the body only repeats it.
    if caller.team_id != body.team_id:
        raise Forbidden("A service event's team is the one its token names.", code="team_mismatch")
    event = await service_events.emit(
        rt,
        name=body.name,
        key=body.key,
        team_id=body.team_id,
        source=source,
        actor=body.actor,
        payload=body.payload,
    )
    return ok(
        {
            "id": event["id"],
            "name": event["name"],
            "key": event["event_key"],
            "status": event["status"],
            "runIds": event["run_ids"],
            "attempts": event["attempts"],
            "woke": event.get("woke") or [],
        },
        status=202,
    )
