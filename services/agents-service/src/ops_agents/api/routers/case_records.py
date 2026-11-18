"""`/v1/cases`: a team's long-lived customer issues and their timelines. The run list stays on `/runs`.

A case belongs to the team the request acts in; another team's or tenant's case answers 404. Every member reads,
opens and works its team's cases (`cases.view`, `cases.create`, `cases.edit`); closing one, or reopening a closed
one, is `cases.manage` and a person's: an agent or workflow may resolve a case but never close it. A service token opens
and works cases with the `cases:*` scopes Settings.service_scopes gives it.

Opening, changing, noting and linking a case each answer in one request transaction (`Tx`): they touch this service's
database only. The list and the case page read the case rows in one transaction and name people through
platform-service (and the page asks files-service and tools-service) after it ends, with no connection held."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, TypeAlias

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_access import can
from ops_engine.store import RunStore
from ops_identity.fastapi import Tx
from ops_service_kit.errors import NotFound, Unprocessable
from ops_service_kit.http import Envelope, In, Json, JsonValue, ListResult, Out
from ops_service_kit.listing import ListQuery
from ops_store import isolation

from ...store.cases import CaseNotFound, CaseRecord, CaseStore, Priority, Status
from ...store.engine import EngineTransactions
from ...store.tenancy import current_team
from ..actors import actor_reads, named_actors
from ..auth import Principal, caller_in, caller_of
from ..case_page import ask_case, assembled, case_reads
from ..deps import Runtime, runtime
from ..envelope import ok
from ..file_names import names_asked_once
from ..runs import graph_store
from ..tool_access import one_read_per_tool
from .engine import StoryLine

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller_in("cases"))]  # noqa: UP040

router = APIRouter(prefix="/v1/cases")
# The kinds a caller adds by hand; `opened`, `field` and `link` are written by the store as the case changes.
NoteKind = Literal["note", "run", "chat", "decision"]
IsoTime = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")]


class CaseIn(In):
    subject: str = Field(min_length=1, max_length=300)
    priority: Priority = "normal"
    # The producer's own key (its run or chat id): opening again with it answers the case already opened.
    producer_key: str | None = Field(default=None, min_length=1, max_length=200)
    customer_id: str | None = Field(default=None, max_length=200)
    customer_name: str | None = Field(default=None, max_length=300)
    assignee: str | None = Field(default=None, max_length=320)
    response_due_at: IsoTime | None = None
    resolution_due_at: IsoTime | None = None


class CasePatch(In):
    subject: str | None = Field(default=None, min_length=1, max_length=300)
    status: Status | None = None
    priority: Priority | None = None
    assignee: str | None = Field(default=None, max_length=320)
    customer_id: str | None = Field(default=None, max_length=200)
    customer_name: str | None = Field(default=None, max_length=300)
    response_due_at: IsoTime | None = None
    resolution_due_at: IsoTime | None = None
    responded_at: IsoTime | None = None


class EventIn(In):
    kind: NoteKind = "note"
    # The run, chat thread or review the entry is about.
    ref: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=10_000)


class LinkIn(In):
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
    fields: dict[str, JsonValue] | None = None
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
    detail: dict[str, JsonValue]
    by: str
    at: str


class CaseDetail(CaseView):
    events: list[CaseEventView]


# The assembled case: docs/services/agents-service/overview.md "Cases" and the approved case page design.
class CaseTypeRef(Out):
    id: str
    version: int
    name: str


class PersonRef(Out):
    email: str
    name: str


class CaseRow(CaseView):
    # Who works the case, by name as its page says it; the list joins it so the console looks nothing up.
    owner: PersonRef | None


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
    raw: JsonValue = None
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
    # None when files-service cannot say; the console shows the id.
    name: str | None
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


class CasePermissions(Out):
    assign: bool
    change_status: bool
    close: bool
    note: bool


class CaseTimer(Out):
    # The case type's deadline field's label, or "Resolution".
    label: str
    due_at: str
    # running, breached or met; paused only for the resolution clock.
    state: str
    left_s: int | None


class LeftItem(Out):
    # task: an open Human Task; action: an approved action the bank's system refused, waiting for a new decision.
    kind: str
    # A person's name, else the deciding team's name.
    who: str
    what: str
    due_at: str | None
    href: str


class WhatsLeft(Out):
    items: list[LeftItem]
    # Nothing left, no linked run still working, not resolved or closed, and the caller may change the status.
    resolvable: bool


class CaseOrigin(Out):
    """How the case's work began: email, request (a form or an API call), event, other, or person (opened by
    hand, with no run)."""

    kind: str
    text: str
    run_id: str | None
    href: str | None


class CaseFeed(Out):
    # Newest first, the run page's lines for each linked run and the case's own timeline worded alike.
    lines: list[StoryLine]
    # Lines past the first 200, counted and not sent.
    more: int


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
    permissions: CasePermissions
    timer: CaseTimer
    whats_left: WhatsLeft
    origin: CaseOrigin
    feed: CaseFeed


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


def _view(row: CaseRecord, now: datetime | None = None) -> dict[str, Any]:
    at = now or datetime.now(UTC)
    running = row.paused_since is None and row.status not in ("resolved", "closed")
    view = CaseView.model_validate(
        row.model_dump(include=set(CaseView.model_fields))
        | {
            "response_left_s": _left(row.response_due_at, at) if running and not row.responded_at else None,
            "resolution_left_s": _left(row.resolution_due_at, at) if running else None,
        }
    )
    return view.model_dump(mode="json", by_alias=True)


async def _visible(store: CaseStore, me: Principal, case_id: str) -> CaseRecord:
    try:
        return await store.get(case_id, [_team(me)])
    except CaseNotFound:
        raise NotFound(f"Case {case_id}") from None


async def _detail(store: CaseStore, row: CaseRecord) -> dict[str, Any]:
    events = [
        CaseEventView.model_validate(e.model_dump(include=set(CaseEventView.model_fields)))
        for e in await store.events(row.id)
    ]
    return {**_view(row), "events": [e.model_dump(mode="json", by_alias=True) for e in events]}


@router.post("", response_model=Envelope[CaseView], status_code=201)
async def open_case(rt: Rt, me: Me, _: Tx, body: CaseIn) -> JSONResponse:
    """Opens a case in the acting team: 201, or 200 with the case a retry with the same producer key opened."""
    team = _team(me)
    can(caller_of(me), "cases", "create", team=team, what="a case")
    opened = await CaseStore(rt.db).open(team_id=team, by=_by(me), **body.model_dump())
    return ok(_view(opened.case), 201 if opened.created else 200)


@router.get("", response_model=Envelope[ListResult[CaseRow]])
async def list_cases(
    *,
    rt: Rt,
    me: Me,
    q: ListQuery,
    status: Annotated[list[Status] | None, Query()] = None,
    priority: Annotated[list[Priority] | None, Query()] = None,
    assignee: str | None = None,
    customer_id: Annotated[str | None, Query(alias="customerId")] = None,
    overdue: bool = False,
) -> JSONResponse:
    """The acting team's cases on the shared list contract, the soonest resolution deadline first, then by id.
    `search` keeps the cases holding every word in the subject, the customer's name or id; `status`, `priority`,
    `assignee` and `customerId` filter (declared here so a value outside a status or priority is refused); `overdue`
    keeps the open ones past their deadline, leaving out a case that waits on the customer."""
    del status, priority, assignee, customer_id  # read from `q.filters`, which holds each value given
    async with isolation.request_transaction():
        listed, rows = await CaseStore(rt.db).page([_team(me)], q, overdue=overdue)
        known = await actor_reads(rt, [r.assignee for r in rows if r.assignee])
    # One batched read of the page's owners, with nothing open; a person platform-service cannot name keeps their email
    # as the name.
    who = await named_actors(rt, known)
    shown = [
        _view(r) | {"owner": {"email": r.assignee, "name": who[r.assignee]["name"]} if r.assignee else None}
        for r in rows
    ]
    return ok({**listed, "data": shown})


@router.get("/{case_id}", response_model=Envelope[CasePage])
async def get_case(rt: Rt, me: Me, case_id: str) -> JSONResponse:
    """The case assembled for its page: its timeline, oldest entry first, and who owns it, its clocks, what
    it waits on and the actions drafted there, its fields in its case type's order, what it links to, its newest
    activity and what the caller may do. Two transactions by design: the first reads the case, its runs and everything
    the page names (a case the caller may not see is not found before any other service is asked); people's names, the
    masking policy, file names and the tools-service policy of each Human Task's calls are then asked with none open;
    the second builds the Human Task views, which need those policies."""
    store = CaseStore(rt.db)
    with one_read_per_tool(), names_asked_once():
        async with isolation.request_transaction():
            row = await _visible(store, me, case_id)
            timeline = await _detail(store, row)
            reads = await case_reads(rt, me, row)
        asked = await ask_case(rt, row, reads)
        async with isolation.request_transaction():
            page = await assembled(rt, me, row, reads, asked)
    return ok(timeline | page)


@router.patch("/{case_id}", response_model=Envelope[CaseDetail])
async def change_case(rt: Rt, me: Me, _: Tx, case_id: str, body: CasePatch) -> JSONResponse:
    """Changes the fields sent, each one a timeline entry. Moving to or from `closed` is `cases.manage` and a
    person's; leaving `waiting_on_customer` moves both deadlines on by the time it waited."""
    store = CaseStore(rt.db)
    row = await _visible(store, me, case_id)
    who = caller_of(me)
    changes = body.model_dump(exclude_unset=True)
    required = [f for f in ("subject", "status", "priority", "response_due_at", "resolution_due_at") if f in changes]
    if any(changes[f] is None for f in required):
        raise Unprocessable("Subject, status, priority and deadlines cannot be cleared.", code="field_required")
    can(who, "cases", "edit", team=row.team_id, what="this case")
    status = changes.get("status")
    if status is not None and "closed" in (status, row.status) and status != row.status:
        if who.kind != "person":
            raise Unprocessable("Only a person closes or reopens a case.", code="person_required")
        can(who, "cases", "manage", team=row.team_id, owner=row.created_by, what="this case")
    await store.change(case_id, changes, by=_by(me))
    return ok(await _detail(store, await store.get(case_id, [row.team_id])))


async def _ref_team(rt: Runtime, kind: str, ref: str) -> str | None:
    """The team that owns what a timeline entry names: a run (an engine run or a v1 thread), the run a decision was
    made on (its review id starts with the run's), or a chat. None when nothing by that id is visible here."""

    run_id = ref.split(":", 1)[0] if kind == "decision" else ref
    if kind in ("run", "decision"):
        run = await RunStore(EngineTransactions(rt.db)).row(run_id)
        if run is not None:
            return run.team_id or None
    thread = await graph_store(rt).thread(run_id)
    return str(thread["team_id"]) if thread is not None and thread.get("team_id") else None


@router.post("/{case_id}/events", response_model=Envelope[CaseDetail], status_code=201)
async def add_event(rt: Rt, me: Me, _: Tx, case_id: str, body: EventIn) -> JSONResponse:
    """Adds a note, or a run, chat or decision the case now covers, to its timeline."""
    store = CaseStore(rt.db)
    row = await _visible(store, me, case_id)
    can(caller_of(me), "cases", "edit", team=row.team_id, what="this case")
    if body.kind == "note" and not body.text:
        raise Unprocessable("A note needs text.", code="text_required")
    if body.kind != "note" and not body.ref:
        raise Unprocessable(f"A {body.kind} entry names the {body.kind} it is about.", code="ref_required")
    # A case names only its own team's runs, chats and decisions: another team's would bring their decisions, reasons
    # and approvers onto this timeline.
    if body.kind != "note" and await _ref_team(rt, body.kind, str(body.ref)) != row.team_id:
        raise NotFound(body.kind.capitalize())
    detail: Json = {"text": body.text} if body.text else {}
    await store.add_event(case_id, body.kind, ref=body.ref, detail=detail, by=_by(me))
    return ok(await _detail(store, row), 201)


@router.post("/{case_id}/links", response_model=Envelope[CaseDetail], status_code=201)
async def link_case(rt: Rt, me: Me, _: Tx, case_id: str, body: LinkIn) -> JSONResponse:
    """Links two cases of the acting team about one issue: an entry on each, naming the other."""
    store = CaseStore(rt.db)
    row = await _visible(store, me, case_id)
    if body.case_id == case_id:
        raise Unprocessable("A case cannot be linked to itself.", code="self_link")
    await _visible(store, me, body.case_id)
    can(caller_of(me), "cases", "edit", team=row.team_id, what="this case")
    await store.link(case_id, body.case_id, by=_by(me))
    return ok(await _detail(store, row), 201)
