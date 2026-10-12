"""Timer routes. `POST /v1/threads/{id}/events`: things that happen to a waiting thread from outside it; a customer
reply restarts the SLA clock of the human step the thread waits on. `POST /v1/threads/{id}/timers/{timerId}/fire`:
the internal fire endpoint every scheduler calls (ADR-0016), authenticated with the service token, not a user."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_contracts.chat import WireModel
from ops_service_kit.errors import Conflict

from ..auth import principal, service_principal
from ..deps import Runtime, runtime
from ..envelope import ok
from ..runs import resolve
from ..schemas import Envelope, ThreadEventResult, TimerFired
from ..timers import REFUSED, fire, restart_on_customer_reply, waiting_with_sla

router = APIRouter(prefix="/v1/threads", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases


class ThreadEvent(WireModel):
    type: Literal["customer_reply"]


@router.post("/{thread_id}/events", response_model=Envelope[ThreadEventResult])
async def thread_event(rt: Rt, thread_id: str, body: ThreadEvent) -> JSONResponse:
    await resolve(rt, thread_id)
    if not await waiting_with_sla(rt, thread_id):
        raise Conflict("This thread is not waiting on a step with an SLA.", code="no_sla_waiting")
    restarted = await restart_on_customer_reply(rt, thread_id)
    return ok({"type": body.type, "restarted": restarted})


internal_router = APIRouter(prefix="/v1/threads", dependencies=[Depends(service_principal)])


@internal_router.post("/{thread_id}/timers/{timer_id}/fire", response_model=Envelope[TimerFired])
async def fire_timer(rt: Rt, thread_id: str, timer_id: str) -> JSONResponse:
    """Idempotent on the timer id; safe to call early, twice or at the same time as another scheduler. 200 with the
    outcome (`fired`, `duplicate`, `not_due`, `not_waiting`, `busy`, `retry`); 409 when the timer will never fire."""
    result = await fire(rt, thread_id, timer_id)
    body = {"timerId": result.timer_id, "status": result.status, "runId": result.run_id, "attempts": result.attempts}
    if result.status in REFUSED:
        raise Conflict(
            f"Timer {timer_id} is {result.status} and will not fire.", code=f"timer_{result.status}", details=body
        )
    return ok(body)
