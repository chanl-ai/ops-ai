"""`/v1/cases`: a team's long-lived customer issues and their timelines (c-128). The run list stays on `/runs`.

A case belongs to the team the request acts in; another team's or tenant's case answers 404. Every member reads,
opens and works its team's cases (`cases.view`, `cases.create`, `cases.edit`); closing one, or reopening a closed
one, is `cases.manage` and a person's: an agent or workflow may resolve a case but never close it (owner,
2026-10-17). A service token opens and works cases with the `cases:*` scopes Settings.service_scopes gives it."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, TypeAlias

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ops_access import can
from ops_contracts.chat import WireModel
from ops_engine.store import RunStore
from ops_service_kit.errors import NotFound, Unprocessable
from ops_service_kit.http import Envelope, ListResult, Pagination

from ...store.cases import CaseNotFound, CaseStore, Priority, Status
from ...store.engine import EngineTransactions
from ...store.tenancy import current_team
from ..auth import Principal, caller_in, caller_of
from ..case_page import assembled
from ..deps import Runtime, runtime
from ..envelope import ok
from ..runs import graph_store
from ..schemas import Out

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller_in("cases"))]  # noqa: UP040

router = APIRouter(prefix="/v1/cases")
# The kinds a caller adds by hand; `opened`, `field` and `link` are written by the store as the case changes.
NoteKind = Literal["note", "run", "chat", "decision"]
IsoTime = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")]


class CaseIn(WireModel):
    subject: str = Field(min_length=1, max_length=300)
    priority: Priority = "normal"
    # The producer's own key (its run or chat id): opening again with it answers the case already opened.
    producer_key: str | None = Field(default=None, min_length=1, max_length=200)
    customer_id: str | None = Field(default=None, max_length=200)
    customer_name: str | None = Field(default=None, max_length=300)
    assignee: str | None = Field(default=None, max_length=320)
    response_due_at: IsoTime | None = None
    resolution_due_at: IsoTime | None = None


class CasePatch(WireModel):
    subject: str | None = Field(default=None, min_length=1, max_length=300)
    status: Status | None = None
    priority: Priority | None = None
    assignee: str | None = Field(default=None, max_length=320)
    customer_id: str | None = Field(default=None, max_length=200)
    customer_name: str | None = Field(default=None, max_length=300)
    response_due_at: IsoTime | None = None
    resolution_due_at: IsoTime | None = None
    responded_at: IsoTime | None = None


class EventIn(WireModel):
    kind: NoteKind = "note"
    # The run, chat thread or review the entry is about.
    ref: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=10_000)


class LinkIn(WireModel):
    case_id: str = Field(min_length=1, max_length=64)


class CaseView(Out):
    id: str
    team_id: str
    producer_key: str | None
    subject: str
    customer_id: str | None
    customer_name: str | None
    status: Status
    assignee: str | None
    priority: Priority
    response_due_at: str
    resolution_due_at: str
    responded_at: str | None
    # Set while the case waits on the customer: both deadlines are paused from then.
    paused_since: str | None
    # What its producer read or worked out, by name (a workflow's Open or Add to case fields).
    fields: dict[str, Any] | None = None
    created_by: str
    created_at: str
    updated_at: str
    # Seconds until each deadline, negative once past; None while paused, once met, or once the case is resolved.
    response_left_s: int | None
    resolution_left_s: int | None


class CaseEventView(Out):
    id: str
    kind: str
    ref: str | None
    detail: dict[str, Any]
    by: str
    at: str


class CaseDetail(CaseView):
    events: list[CaseEventView]


# The assembled case (c-291): docs/services/agents-service/overview.md "Cases" and the approved case page design.
class CaseTypeRef(Out):
    id: str
    version: int
    name: str


class PersonRef(Out):
    email: str
    name: str


class NamedRef(Out):
    id: str
    name: str


class CustomerRef(NamedRef):
    href: str


class Clock(Out):
    state: Literal["running", "met", "breached", "paused"]
    due_at: str
    left_s: int | None
    met_at: str | None


class Sla(Out):
    response: Clock
    resolution: Clock
    paused_since: str | None


class NextAction(Out):
    kind: Literal["human_task"]
    label: str
    owner: str | None
    due_at: str | None
    href: str


class TypedField(Out):
    key: str
    label: str
    type: str
    display: str
    raw: Any = None
    file_id: str | None
    required: bool
    declared: bool
    edited: bool


class Assignee(Out):
    name: str


class WaitingTask(Out):
    task_id: str
    title: str
    assignee: Assignee | None
    group: str | None
    opened_at: str
    due_at: str | None
    href: str


class DraftedAction(Out):
    id: str
    task_id: str
    label: str
    kind: Literal["reply", "tool"]
    status: str
    approvals_given: int
    approvals_needed: int
    summary: str | None
    href: str


class FileLink(Out):
    file_id: str
    name: str
    viewer_href: str


class RunLink(Out):
    id: str
    workflow_name: str
    state: str
    href: str


class EmailLink(Out):
    id: str
    subject: str
    direction: Literal["in"]
    at: str
    href: str


class CaseLink(Out):
    id: str
    subject: str
    status: str
    relation: Literal["linked", "same_customer"]
    href: str


class AllHrefs(Out):
    runs: str
    emails: str
    cases: str | None


class Links(Out):
    files: list[FileLink]
    runs: list[RunLink]
    emails: list[EmailLink]
    cases: list[CaseLink]
    all_hrefs: AllHrefs


class WorkflowRef(NamedRef):
    href: str


class ActivityLine(Out):
    at: str
    actor_name: str
    text: str
    href: str | None


class RecentActivity(Out):
    recent: list[ActivityLine]
    total: int
    all_href: str


class CasePermissions(Out):
    assign: bool
    change_status: bool
    close: bool
    note: bool


class CasePage(CaseDetail):
    case_type: CaseTypeRef | None
    owner: PersonRef | None
    team: NamedRef
    customer: CustomerRef | None
    sla: Sla
    next_action: NextAction | None
    typed_fields: list[TypedField]
    waiting: list[WaitingTask]
    waiting_all_href: str
    actions: list[DraftedAction]
    links: Links
    workflow: WorkflowRef | None
    activity: RecentActivity
    permissions: CasePermissions


def _team(me: Principal) -> str:
    team = current_team() or me.team_id
    if not team:
        raise Unprocessable(
            "Choose a team with the X-Team-Id header; a case belongs to one team.", code="team_required"
        )
    return team


def _by(me: Principal) -> str:
    return me.email or me.sub


def _left(due: str, now: datetime) -> int:
    return int((datetime.fromisoformat(due.replace("Z", "+00:00")) - now).total_seconds())


def _view(row: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    at = now or datetime.now(UTC)
    running = row["paused_since"] is None and row["status"] not in ("resolved", "closed")
    fields: dict[str, Any] = {k: v for k, v in row.items() if k in CaseView.model_fields}
    fields["response_left_s"] = _left(row["response_due_at"], at) if running and not row["responded_at"] else None
    fields["resolution_left_s"] = _left(row["resolution_due_at"], at) if running else None
    return CaseView(**fields).model_dump(mode="json", by_alias=True)


async def _visible(store: CaseStore, me: Principal, case_id: str) -> dict[str, Any]:
    try:
        return await store.get(case_id, [_team(me)])
    except CaseNotFound:
        raise NotFound(f"Case {case_id}") from None


async def _detail(store: CaseStore, row: dict[str, Any]) -> dict[str, Any]:
    events = [CaseEventView(**{k: e[k] for k in CaseEventView.model_fields}) for e in await store.events(row["id"])]
    return {**_view(row), "events": [e.model_dump(mode="json", by_alias=True) for e in events]}


@router.post("", response_model=Envelope[CaseView], status_code=201)
async def open_case(rt: Rt, me: Me, body: CaseIn) -> JSONResponse:
    """Opens a case in the acting team: 201, or 200 with the case a retry with the same producer key opened."""
    team = _team(me)
    can(caller_of(me), "cases", "create", team=team, what="a case")
    opened = await CaseStore(rt.db).open(team_id=team, by=_by(me), **body.model_dump())
    return ok(_view(opened.case), 201 if opened.created else 200)


class CasesQuery(BaseModel):
    status: list[Status] = Field(default_factory=list[Status])
    priority: list[Priority] = Field(default_factory=list[Priority])
    assignee: str | None = None
    customerId: str | None = None  # noqa: N815 - the console's query parameter
    overdue: bool = False
    # Words in the subject, the customer's name or id.
    search: str | None = Field(default=None, max_length=200)
    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=25, ge=1, le=100)  # noqa: N815


@router.get("", response_model=Envelope[ListResult[CaseView]])
async def list_cases(rt: Rt, me: Me, q: Annotated[CasesQuery, Query()]) -> JSONResponse:
    """The acting team's cases, the soonest resolution deadline first. `overdue` keeps the open ones past it, leaving
    out a case that waits on the customer."""
    rows, total = await CaseStore(rt.db).list(
        [_team(me)],
        status=list(q.status),
        priority=list(q.priority),
        assignee=q.assignee,
        customer_id=q.customerId,
        overdue=q.overdue,
        search=q.search,
        page=q.page,
        size=q.pageSize,
    )
    pages = max(1, math.ceil(total / q.pageSize))
    pagination = Pagination(
        page=q.page, page_size=q.pageSize, total=total, total_pages=pages, has_next=q.page < pages, has_prev=q.page > 1
    )
    result = {"data": [_view(r) for r in rows], "pagination": pagination.model_dump(by_alias=True), "facets": {}}
    return ok(result)


@router.get("/{case_id}", response_model=Envelope[CasePage])
async def get_case(rt: Rt, me: Me, case_id: str) -> JSONResponse:
    """The case assembled for its page (c-291): its timeline, oldest entry first, and who owns it, its clocks, what
    it waits on and the actions drafted there, its fields in its case type's order, what it links to, its newest
    activity and what the caller may do."""
    store = CaseStore(rt.db)
    row = await _visible(store, me, case_id)
    return ok(await _detail(store, row) | await assembled(rt, me, row))


@router.patch("/{case_id}", response_model=Envelope[CaseDetail])
async def change_case(rt: Rt, me: Me, case_id: str, body: CasePatch) -> JSONResponse:
    """Changes the fields sent, each one a timeline entry. Moving to or from `closed` is `cases.manage` and a
    person's; leaving `waiting_on_customer` moves both deadlines on by the time it waited."""
    store = CaseStore(rt.db)
    row = await _visible(store, me, case_id)
    who = caller_of(me)
    changes = body.model_dump(exclude_unset=True)
    required = [f for f in ("subject", "status", "priority", "response_due_at", "resolution_due_at") if f in changes]
    if any(changes[f] is None for f in required):
        raise Unprocessable("Subject, status, priority and deadlines cannot be cleared.", code="field_required")
    can(who, "cases", "edit", team=row["team_id"], what="this case")
    status = changes.get("status")
    if status is not None and "closed" in (status, row["status"]) and status != row["status"]:
        if who.kind != "person":
            raise Unprocessable("Only a person closes or reopens a case.", code="person_required")
        can(who, "cases", "manage", team=row["team_id"], owner=row["created_by"], what="this case")
    await store.change(case_id, changes, by=_by(me))
    return ok(await _detail(store, await store.get(case_id, [row["team_id"]])))


async def _ref_team(rt: Runtime, kind: str, ref: str) -> str | None:
    """The team that owns what a timeline entry names: a run (an engine run or a v1 thread), the run a decision was
    made on (its review id starts with the run's), or a chat. None when nothing by that id is visible here."""

    run_id = ref.split(":", 1)[0] if kind == "decision" else ref
    if kind in ("run", "decision"):
        run = await RunStore(EngineTransactions(rt.db)).get(run_id)
        if run is not None:
            return str(run.get("team_id") or "") or None
    thread = await graph_store(rt).thread(run_id)
    return str(thread["team_id"]) if thread is not None and thread.get("team_id") else None


@router.post("/{case_id}/events", response_model=Envelope[CaseDetail], status_code=201)
async def add_event(rt: Rt, me: Me, case_id: str, body: EventIn) -> JSONResponse:
    """Adds a note, or a run, chat or decision the case now covers, to its timeline."""
    store = CaseStore(rt.db)
    row = await _visible(store, me, case_id)
    can(caller_of(me), "cases", "edit", team=row["team_id"], what="this case")
    if body.kind == "note" and not body.text:
        raise Unprocessable("A note needs text.", code="text_required")
    if body.kind != "note" and not body.ref:
        raise Unprocessable(f"A {body.kind} entry names the {body.kind} it is about.", code="ref_required")
    # A case names only its own team's runs, chats and decisions: another team's would bring their decisions, reasons
    # and approvers onto this timeline.
    if body.kind != "note" and await _ref_team(rt, body.kind, str(body.ref)) != row["team_id"]:
        raise NotFound(body.kind.capitalize())
    detail = {"text": body.text} if body.text else {}
    await store.add_event(case_id, body.kind, ref=body.ref, detail=detail, by=_by(me))
    return ok(await _detail(store, row), 201)


@router.post("/{case_id}/links", response_model=Envelope[CaseDetail], status_code=201)
async def link_case(rt: Rt, me: Me, case_id: str, body: LinkIn) -> JSONResponse:
    """Links two cases of the acting team about one issue: an entry on each, naming the other."""
    store = CaseStore(rt.db)
    row = await _visible(store, me, case_id)
    if body.case_id == case_id:
        raise Unprocessable("A case cannot be linked to itself.", code="self_link")
    await _visible(store, me, body.case_id)
    can(caller_of(me), "cases", "edit", team=row["team_id"], what="this case")
    await store.link(case_id, body.case_id, by=_by(me))
    return ok(await _detail(store, row), 201)
