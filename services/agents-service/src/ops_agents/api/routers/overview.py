"""`/v1/overview`: what waits on a person, counted on the server (c-129). Reviews come from the same list Human Tasks
reads (hitl_facade.all_reviews), so the two never disagree; cases from the cases store, in the team the request acts
in."""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_service_kit.http import Envelope

from ...store.cases import CaseStore
from ...store.tenancy import current_team
from .. import hitl_facade
from ..auth import Principal, principal, teams_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Out

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

router = APIRouter(prefix="/v1/overview")
URGENT = 5


class CaseCounts(Out):
    # Open or waiting on us: a person has to act.
    open: int
    # Past the resolution deadline and not paused.
    breaching: int
    # Cases with a review open on one of their runs.
    awaiting_approval: int


class OverviewCounts(Out):
    open_reviews: int
    overdue_reviews: int
    # The open reviews soonest past their SLA, for the Needs a decision table.
    urgent_reviews: list[dict[str, Any]]
    cases: CaseCounts


@router.get("", response_model=Envelope[OverviewCounts])
async def overview(rt: Rt, me: Me) -> JSONResponse:
    rows = await hitl_facade.all_reviews(rt)
    open_rows = [r for r in rows if hitl_facade.REVIEW_VIEWS["open"](r)]
    overdue = [r for r in rows if hitl_facade.REVIEW_VIEWS["overdue"](r)]
    # A review with no SLA sorts last: nothing makes it urgent.
    urgent = sorted(open_rows, key=lambda r: (r.get("slaMinutes") is None, r.get("slaMinutes") or 0))[:URGENT]
    team = current_team()
    counts = await CaseStore(rt.db).counts([team] if team else teams_of(me))
    awaiting = len({r["caseId"] for r in open_rows if r.get("caseId")})
    body = OverviewCounts(
        open_reviews=len(open_rows),
        overdue_reviews=len(overdue),
        urgent_reviews=urgent,
        cases=CaseCounts(open=counts["needs"], breaching=counts["breaching"], awaiting_approval=awaiting),
    )
    return ok(body.model_dump(mode="json", by_alias=True))
