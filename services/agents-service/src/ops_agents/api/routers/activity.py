"""GET /v1/activity (c-201): everything that happened in the caller's teams on one list, filtered by kind, team,
status and source, with counts per kind and status for the "View activity" buttons on the channel, agent and workflow
pages. The rows are joined by the store (store/activity.py); this router decides which teams each kind is read in."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ops_access import can
from ops_service_kit.errors import Forbidden, NotFound, Unprocessable
from ops_service_kit.http import Envelope, ListResult, paged

from ...store.activity import KINDS, Activity, Filters, Scope
from ...store.cases import CaseNotFound, CaseStore
from ...store.tenancy import current_team
from ..actors import ActorView, actors
from ..auth import Principal, caller_in, caller_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Out

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller_in("workflows"))]  # noqa: UP040

router = APIRouter(prefix="/v1/activity")

# The area each kind is read under; a chat is read under the chat rule (`_chat_teams`).
KindName = Literal[
    "workflow_run", "agent_run", "chat", "email", "decision", "tool_call", "case", "system_workflow", "reminder"
]
StatusName = Literal["running", "waiting", "done", "failed", "skipped"]
AREA = {
    "workflow_run": "workflows",
    "email": "workflows",
    "agent_run": "agents",
    "decision": "reviews",
    "case": "cases",
    # A shipped system workflow belongs to no team: read where the caller may view workflows in a team asked about.
    "system_workflow": "workflows",
    # A reminder on a waiting review (c-277): read where the caller may view the run team's reviews.
    "reminder": "reviews",
}
SOURCE_TYPES = ("workflow", "agent", "channel", "case")


class Source(Out):
    type: Literal["workflow", "agent", "channel", "case"]
    id: str
    name: str


class Ref(Out):
    # run: a workflow run; thread: an agent run; chat: a chat thread; review: a Human Task; email: a received email
    # that started no run; case: a case; workflow: a workflow definition.
    kind: Literal["run", "thread", "chat", "review", "email", "case", "workflow"]
    id: str


class ActivityRow(Out):
    # `<kind>:<the source record's id>`; unique across kinds.
    id: str
    kind: KindName
    title: str
    status: StatusName
    # The source's own word: succeeded, cancelled, duplicate, filtered, daily_cap, approved, rejected...
    outcome: str | None
    team_id: str | None
    source: Source
    actor: ActorView
    at: str
    ref: Ref


class ActivityQuery(BaseModel):
    kind: list[KindName] = Field(default_factory=list[KindName])
    status: list[StatusName] = Field(default_factory=list[StatusName])
    # `type:id`, e.g. workflow:levy_case or channel:levy@northfield.example; repeat to keep several.
    source: list[str] = Field(default_factory=list)
    # The selected team when left out; `all` for every team the caller is in; or one of those teams by id.
    team: str | None = None
    since: str | None = None
    until: str | None = None
    # One case: its own entries and everything about the runs and chats linked to it (c-341).
    case: str | None = None
    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=25, ge=1, le=100)  # noqa: N815 - the console's query parameter


def _may(me: Principal, area: str, action: str, team: str) -> str | None:
    """The scope `can` grants in `team`, or None when it grants nothing. Asked of every team the caller is in, not
    only the one the request acts in: `team=all` lists them together."""
    try:
        return can(caller_of(me), area, action, team=team, what="this", from_any_team=True)
    except Forbidden:
        return None


def _teams(me: Principal, team: str | None) -> tuple[str, ...] | None:
    """The teams asked about: None for a dev caller, which reads across teams."""
    if me.team_ids is None:
        return None
    if team == "all":
        return me.team_ids
    chosen = team or current_team() or me.team_id
    if chosen not in me.team_ids:
        raise NotFound(f"Team {chosen}")
    return (chosen,)


def scope_of(me: Principal, team: str | None) -> Scope:
    asked = _teams(me, team)
    if asked is None:
        return Scope(teams=dict.fromkeys(KINDS), owner=me.email, chat_all=None)
    teams: dict[str, tuple[str, ...] | None] = {
        kind: tuple(t for t in asked if _may(me, area, "view", t)) for kind, area in AREA.items()
    }
    # chat.view is `own` for every built-in role while chatThreadsOwnerOnly is on (its default); `all` only with it off.
    scopes = {t: _may(me, "chat", "view", t) for t in asked}
    teams["chat"] = tuple(t for t, s in scopes.items() if s)
    # A tool call is read where its thread is (store/activity.py); the kind is present when anything could be.
    teams["tool_call"] = asked
    return Scope(teams=teams, owner=me.email, chat_all=tuple(t for t, s in scopes.items() if s == "all"))


def _sources(raw: list[str]) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for s in raw:
        kind, _, sid = s.partition(":")
        if kind not in SOURCE_TYPES or not sid:
            raise Unprocessable(f"A source is type:id with type one of {', '.join(SOURCE_TYPES)}.", code="bad_source")
        out.append((kind, sid))
    return tuple(out)


def row_view(r: dict[str, Any], who: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": f"{r['kind']}:{r['row_id']}",
        "kind": r["kind"],
        "title": r["title"],
        "status": r["status"],
        "outcome": r["outcome"],
        "teamId": r["team_id"],
        "source": {"type": r["source_type"], "id": r["source_id"] or "", "name": r["source_name"] or ""},
        "actor": who.get(str(r["actor"] or "")) or {"kind": "person", "id": "", "name": ""}
        if r["kind"] != "email"
        else {"kind": "sender", "id": r["actor"], "name": r["actor"]},
        "at": r["at"],
        "ref": {"kind": r["ref_kind"], "id": r["ref_id"]},
    }


async def _case(rt: Runtime, scope: Scope, case_id: str) -> tuple[str, str]:
    """The case and its team, when the caller may view cases in that team; another team's case is not found."""
    try:
        teams = scope.teams.get("case", ())
        row = await CaseStore(rt.db).get(case_id, None if teams is None else list(teams))
    except CaseNotFound:
        raise NotFound(f"Case {case_id}") from None
    return case_id, str(row["team_id"])


@router.get("", response_model=Envelope[ListResult[ActivityRow]])
async def list_activity(rt: Rt, me: Me, q: Annotated[ActivityQuery, Query()]) -> JSONResponse:
    """What happened, newest first, a page at a time, in the selected team (`team=all`: every team the caller is in).
    Each kind is read where the caller may view its area, and a chat only where they may read it: their own while the
    workspace keeps chats private. `facets.kind` and `facets.status` count the rows under the other filters."""
    scope = scope_of(me, q.team)
    case = await _case(rt, scope, q.case) if q.case else None
    filters = Filters(
        kinds=tuple(q.kind),
        statuses=tuple(q.status),
        sources=_sources(q.source),
        since=q.since,
        until=q.until,
        case=case,
    )
    found = await Activity(rt.db).page(scope, filters, page=q.page, page_size=q.pageSize)
    who = await actors(rt, [str(r["actor"] or "") for r in found.rows if r["kind"] != "email"])
    listed = paged([row_view(r, who) for r in found.rows], found.total, q.page, q.pageSize)
    return ok(listed | {"facets": {"kind": found.by_kind, "status": found.by_status}})
