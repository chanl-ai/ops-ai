"""POST /v1/runs/{run_id}/steps/{step}/resume (c-525): an outside system hands a workflow step it was given the work of
its result, and the run carries on.

No person calls it: the bearer token is the step's own resume token (api/engine_resume.py), bound to the run, step,
pass, interrupt and team, so it resumes that one pause and nothing else. 401 for a token this service did not sign or
one that expired, 404 for a run its team does not see, 409 `already_resumed` once the pause has been resumed (by this
callback, its event or its time limit).
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ops_engine.store import RunStore
from ops_service_kit.errors import Conflict, NotFound, Unauthorized
from ops_service_kit.http import Envelope
from ops_store import isolation

from ...store.engine import EngineTransactions
from ..deps import Runtime, runtime
from ..engine_resume import BadResumeToken, ResumeClaim, read_token, resumed
from ..envelope import ok
from ..schemas import Out

router = APIRouter(prefix="/v1/runs")
Rt = Annotated[Runtime, Depends(runtime)]


class ResumeBody(BaseModel):
    """The outside system's result, whatever its fields: the step goes on with it as its output, and a step that sets
    an answer schema names the fields later steps read."""

    model_config = ConfigDict(extra="allow")


class ResumeOut(Out):
    run_id: str
    status: str


# The kind of context a resume token sets: an outside system holding one step's token, not a person or a service.
RESUME_CALLBACK = "resume-callback"


async def resume_caller(
    rt: Rt, run_id: str, step: str, authorization: Annotated[str | None, Header()] = None
) -> ResumeClaim:
    """How an outside system authenticates a resume: the step's own signed token, which enters the run's team for the
    request (check_standards rule 5 counts it as an auth dependency). A person's token or a service token is refused,
    since either could resume any step its team can see."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    try:
        claim = read_token(rt.settings.review_key.get_secret_value(), token)
    except BadResumeToken as e:
        raise Unauthorized(f"Not a resume token for this step: {e}.", code="bad_resume_token") from e
    if claim.run_id != run_id or claim.node != step:
        raise Unauthorized("This token resumes another step.", code="bad_resume_token")
    isolation.enter(claim.tenant, claim.team, kind=RESUME_CALLBACK)
    return claim


@router.post("/{run_id}/steps/{step}/resume", status_code=202, response_model=Envelope[ResumeOut])
async def resume_step(
    rt: Rt, run_id: str, step: str, body: ResumeBody, claim: Annotated[ResumeClaim, Depends(resume_caller)]
) -> JSONResponse:
    """Resumes the step parked on outside work with the posted result, which the step goes on with."""
    run = await RunStore(EngineTransactions(rt.db)).get(run_id)
    if run is None:
        raise NotFound("The run")
    waiting = cast(dict[str, Any], run.get("waiting") or {})
    current = (
        run.get("status") == "waiting"
        and waiting.get("interruptId") == claim.interrupt_id
        and str(waiting.get("node")) == claim.node
        and int(waiting.get("iteration") or 0) == claim.iteration
    )
    if not current or not await resumed(rt.db, run, waiting, {"callback": body.model_dump()}, source="callback"):
        raise Conflict("This step was already resumed.", code="already_resumed")
    return ok({"runId": run_id, "status": "queued"}, status=202)
