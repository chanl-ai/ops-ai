"""GET /v1/prompts/variables: the `{key}` placeholders a run fills in an agent's instructions, so the console's
instructions editor offers only what a turn can fill. The kernel fails a turn whose instructions name a key the turn has
no value for (ops_agent_kernel/context.py `_fill`), and no run passes variables yet, so the list is empty until one
does; each key a run starts passing is added to RUN_VARIABLES beside it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_service_kit.http import Envelope

from ..auth import Principal, principal, reader_of
from ..envelope import ok
from ..schemas import PromptVariable

RUN_VARIABLES: tuple[PromptVariable, ...] = ()

router = APIRouter(prefix="/v1/prompts/variables", dependencies=[Depends(principal)])


@router.get("", response_model=Envelope[list[PromptVariable]])
async def list_prompt_variables(_: Annotated[Principal, Depends(reader_of("agents"))]) -> JSONResponse:
    return ok(list(RUN_VARIABLES))
