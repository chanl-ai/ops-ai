"""`POST /v1/platform-events`, as every service that acts on platform-service's events serves it: delivered by
platform-service's outbox relay, as that service, for the event's tenant and team.

One route for every event: a service passes its handlers, each with the right its caller must hold, so a new event is
a new handler, never a new route. An event with no handler is answered as not handled, so it never holds the outbox.
Every handler is idempotent: delivery is at least once."""

# No `from __future__ import annotations`: FastAPI resolves the request model at import.

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_identity import CurrentService
from ops_service_kit.errors import ValidationFailed
from ops_service_kit.http import Envelope, Out, error_responses, ok

from .check import can

# A team made in platform-service (store/teams.py, the seed): each service writes the team's defaults.
TEAM_CREATED = "team.created"
# A member removed from a team (platform-service store/members.py): their own accounts on its apps go.
MEMBER_REMOVED = "member.removed"


@dataclass(frozen=True)
class Handler:
    # The right, as (area, action), the reporting service holds to have this event acted on.
    area: str
    action: str
    # (tenant, team, payload): acts on the event; returns how many records it changed.
    act: Callable[[str, str, dict[str, Any]], Awaitable[int]]


class PlatformEventIn(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    key: str = Field(min_length=1, max_length=200)
    team_id: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict[str, Any])
    # Who made the change, as platform-service recorded it.
    actor: str | None = Field(default=None, max_length=320)


class PlatformEventOut(Out):
    handled: bool
    changed: int = 0


def platform_events_router(handlers: dict[str, Handler], *, tags: tuple[str, ...] = ("gateway",)) -> APIRouter:
    """The route over `handlers`; `tags` are the API document's family for it (a service that tags at mount passes
    none)."""
    r = APIRouter(tags=list(tags), responses=error_responses())

    @r.post("/v1/platform-events", response_model=Envelope[PlatformEventOut])
    async def platform_event(body: PlatformEventIn, caller: CurrentService) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """One event platform-service reports, acted on in the team its token names; the body only repeats it."""
        handler = handlers.get(body.name)
        if handler is None:
            return ok(PlatformEventOut(handled=False).model_dump(by_alias=True))
        can(caller, handler.area, handler.action, what=f"the {body.name} event")
        if caller.team_id != body.team_id:
            raise ValidationFailed("A platform event's team is the one its token names.", code="team_mismatch")
        changed = await handler.act(caller.tenant_id, body.team_id, body.payload)
        return ok(PlatformEventOut(handled=True, changed=changed).model_dump(by_alias=True))

    return r
