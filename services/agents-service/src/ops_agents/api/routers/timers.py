"""Thread events. `POST /v1/threads/{id}/events`: things that happen to a waiting thread from outside it; a customer
reply restarts the SLA clock of the human step the thread waits on. Timers fire in-process from the PostgreSQL poller
(api/timers.py); no HTTP route fires one (c-168)."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_contracts.chat import WireModel
from ops_service_kit.errors import Conflict
from ops_service_kit.http import Envelope

from ..auth import Principal, principal, require_builder
from ..deps import Runtime, runtime
from ..envelope import ok
from ..runs import resolve
from ..schemas import ThreadEventResult
from ..timers import restart_on_customer_reply, waiting_with_sla

router = APIRouter(prefix="/v1/threads", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


class ThreadEvent(WireModel):
    type: Literal["customer_reply"]


@router.post("/{thread_id}/events", response_model=Envelope[ThreadEventResult])
async def thread_event(rt: Rt, me: Me, thread_id: str, body: ThreadEvent) -> JSONResponse:
    """A channel event, as the mailbox adapter delivers it: a builder or admin of the thread's team, the role the
    inbox route takes, since restarting an SLA clock changes when the case escalates."""
    row, _ = await resolve(rt, thread_id)
    require_builder(
        me,
        area="workflows",
        team_id=row["team_id"] or me.team_id,
        action="post an event to",
        what="this thread",
    )
    if not await waiting_with_sla(rt, thread_id):
        raise Conflict("This thread is not waiting on a step with an SLA.", code="no_sla_waiting")
    restarted = await restart_on_customer_reply(rt, thread_id)
    return ok({"type": body.type, "restarted": restarted})
