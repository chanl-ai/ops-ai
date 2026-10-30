"""`/v1/overview`: what waits on a person, counted on the server (c-129). Reviews come from the same list Human Tasks
reads (hitl_facade.all_reviews), so the two never disagree; cases from the cases store, in the team the request acts
in. The Overview page, the sidebar's count and Chat's hints read the lists here already joined (c-552), so the console
fetches nothing beside this one request."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_engine.store import RunStore
from ops_service_kit.http import Envelope

from ...store.cases import CaseStore
from ...store.engine import EngineTransactions
from ...store.tenancy import current_team
from .. import engine_reviews, hitl_facade
from ..auth import Principal, principal, teams_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Out
from ..tool_access import one_read_per_tool

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

router = APIRouter(prefix="/v1/overview")
URGENT = 5
# Rows per Overview list; each widget links to its full page for the rest.
LISTED = 5


class CaseCounts(Out):
    # Open or waiting on us: a person has to act.
    open: int
    # Past the resolution deadline and not paused.
    breaching: int
    # Cases with a review open on one of their runs.
    awaiting_approval: int


class OverviewListCounts(Out):
    # Open Human Tasks assigned to the caller: Human Tasks' "Assigned to me" count.
    waiting_for_me: int
    # Runs running or waiting on a person.
    runs_in_flight: int
    # Cases due by the end of today (UTC) or already past, not resolved and not waiting on the customer.
    cases_due: int


class OverviewTaskRow(Out):
    id: str
    title: str
    workflow_name: str | None = None
    case_id: str | None = None
    created_at: str
    due_at: str | None = None


class OverviewRunRow(Out):
    id: str
    workflow_id: str
    subject: str
    state: str
    started_at: str


class OverviewCaseRow(Out):
    id: str
    subject: str
    customer_name: str | None = None
    status: str
    resolution_due_at: str | None = None


class OverviewCounts(Out):
    open_reviews: int
    overdue_reviews: int
    # The open reviews soonest past their SLA, for the Needs a decision table.
    urgent_reviews: list[dict[str, Any]]
    cases: CaseCounts
    counts: OverviewListCounts
    # Oldest first: the task waiting longest comes first.
    waiting_for_me: list[OverviewTaskRow]
    # Newest first.
    runs_in_flight: list[OverviewRunRow]
    # Soonest resolution deadline first.
    cases_due: list[OverviewCaseRow]


@router.get("", response_model=Envelope[OverviewCounts])
async def overview(rt: Rt, me: Me) -> JSONResponse:
    with one_read_per_tool():
        rows = await hitl_facade.all_reviews(rt)
        open_rows = [r for r in rows if hitl_facade.REVIEW_VIEWS["open"](r)]
        overdue = [r for r in rows if hitl_facade.REVIEW_VIEWS["overdue"](r)]
        # A review with no SLA sorts last: nothing makes it urgent.
        urgent = sorted(open_rows, key=lambda r: (r.get("slaMinutes") is None, r.get("slaMinutes") or 0))[:URGENT]
        urgent = await engine_reviews.expand(rt, urgent)
        names = {me.email, me.name}
        mine = sorted((r for r in open_rows if r.get("assignee") in names), key=lambda r: str(r.get("createdAt") or ""))
        mine_listed = await engine_reviews.expand(rt, mine[:LISTED])
    team = current_team()
    teams = [team] if team else teams_of(me)
    # The engine's runs, as the Runs page lists them: newest first, each named by its workflow version.
    flight, flight_total, _ = await RunStore(EngineTransactions(rt.db)).page(
        statuses=["queued", "running", "waiting"], team_id=team, limit=LISTED
    )
    now = datetime.now(UTC)
    store = CaseStore(rt.db)
    counts = await store.counts(teams)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    due_rows, due_total = await store.list(
        teams, due_before=tomorrow.isoformat(timespec="milliseconds").replace("+00:00", "Z"), size=LISTED
    )
    awaiting = len({r["caseId"] for r in open_rows if r.get("caseId")})
    body = OverviewCounts(
        open_reviews=len(open_rows),
        overdue_reviews=len(overdue),
        urgent_reviews=urgent,
        cases=CaseCounts(open=counts["needs"], breaching=counts["breaching"], awaiting_approval=awaiting),
        counts=OverviewListCounts(waiting_for_me=len(mine), runs_in_flight=flight_total, cases_due=due_total),
        waiting_for_me=[
            OverviewTaskRow(
                id=str(r["id"]),
                title=str(r.get("title") or "Human Task"),
                workflow_name=r.get("workflowName"),
                case_id=r.get("caseId"),
                created_at=str(r["createdAt"]),
                due_at=r.get("dueAt"),
            )
            for r in mine_listed
        ],
        runs_in_flight=[
            OverviewRunRow(
                id=str(r["id"]),
                workflow_id=str(r["workflow_id"]),
                subject=str(r.get("workflow_name") or r["workflow_id"]),
                state="waiting" if r["status"] == "waiting" else "running",
                started_at=str(r["created_at"]),
            )
            for r in flight
        ],
        cases_due=[
            OverviewCaseRow(
                id=str(r["id"]),
                subject=str(r["subject"]),
                customer_name=r.get("customer_name"),
                status=str(r["status"]),
                resolution_due_at=r.get("resolution_due_at"),
            )
            for r in due_rows
        ],
    )
    return ok(body.model_dump(mode="json", by_alias=True))
