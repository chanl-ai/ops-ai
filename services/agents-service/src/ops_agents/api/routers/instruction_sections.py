"""/v1/agent-instruction-sections: the workspace's list of sections a builder adds to an agent's brief, in the order
the prompt writes them (`app/instruction_sections.py`). Anyone who can view agents reads it, since the agent editor's
Add section menu is built from it; replacing or resetting it is settings.manage in the team the request acts in."""

from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_access import can
from ops_service_kit.http import Envelope, Json
from ops_service_kit.logging import get_logger

from ...app import instruction_sections as sections
from ...app.instruction_sections import SectionList, SectionListIn
from ...store.instruction_sections import InstructionSections
from ...store.tenancy import current_team
from ..auth import Principal, caller_of, principal, reader_of
from ..deps import Runtime, runtime
from ..envelope import ok

log = get_logger("ops_agents.instruction_sections")
router = APIRouter(prefix="/v1/agent-instruction-sections", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040
Reader: TypeAlias = Annotated[Principal, Depends(reader_of("agents"))]  # noqa: UP040


def _wire(listing: SectionList) -> Json:
    return listing.model_dump(mode="json", by_alias=True)


def _may_change(me: Principal) -> None:
    # In the team the request acts in, not the Security team: the list is the editor's, which a team's Admin keeps.
    team = current_team() or me.team_id
    can(caller_of(me), "settings", "manage", team=team, what="the agent instruction sections", in_team=True)


@router.get("", response_model=Envelope[SectionList])
async def get_instruction_sections(rt: Rt, _: Reader) -> JSONResponse:
    """The workspace's list, or the default when it has saved none."""
    return ok(_wire(await sections.effective(InstructionSections(rt.db))))


@router.put("", response_model=Envelope[SectionList])
async def put_instruction_sections(rt: Rt, me: Me, body: SectionListIn) -> JSONResponse:
    """Replaces the list with the one sent (422 `validation_failed` naming `sections` when it breaks a rule). Agents
    already saved keep the prompt they were saved with; the next save of each is written in the new order."""
    _may_change(me)
    listing = await sections.replace(InstructionSections(rt.db), body, by=me.email)
    log.info("agent_instruction_sections_saved", by=me.email, sections=len(listing.sections))
    return ok(_wire(listing))


@router.delete("", response_model=Envelope[SectionList])
async def reset_instruction_sections(rt: Rt, me: Me) -> JSONResponse:
    """Resets the list to the default and returns it; 200 when it already was."""
    _may_change(me)
    listing = await sections.reset(InstructionSections(rt.db))
    log.info("agent_instruction_sections_reset", by=me.email)
    return ok(_wire(listing))
