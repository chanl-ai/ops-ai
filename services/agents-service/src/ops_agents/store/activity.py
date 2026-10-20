"""Everything that happened in a team, as one list (c-201): workflow runs, agent runs, chats, emails received, Human
Task decisions, tool calls, what was done on a case and shipped system workflow updates (c-317), each read from the
table that records it and joined into one query, so the console pages and counts it without merging lists of its own.
Filtered to one case (c-341), the list is the case's own entries and every row about a run or chat linked to it.

Every source is selected into the same columns and unioned; filters, the page and the facet counts all run on that one
union inside one transaction. Which teams a kind is read in is decided by the caller (`Scope`), never here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_engine import default_registry
from ops_engine.store.tables import engine_definitions, engine_runs, engine_steps, engine_work
from ops_store import Guarantee

from .agent_registry import publish_requests
from .cases import case_events, cases
from .events import thread_events
from .graphs import graph_threads
from .mailboxes import mailboxes
from .reviews import review_decisions
from .service_events import service_events
from .tenancy import current_tenant, tenant_tx
from .trigger_events import trigger_events
from .widget_deployments import widget_deployments

Kind = Literal[
    "workflow_run", "agent_run", "chat", "email", "decision", "tool_call", "case", "system_workflow", "reminder"
]
KINDS: tuple[Kind, ...] = (
    "workflow_run",
    "agent_run",
    "chat",
    "email",
    "decision",
    "tool_call",
    "case",
    "system_workflow",
    "reminder",
)
# A case entry as a sentence, by its kind (store/cases.py EventKind). A `decision` entry is left out: the decision is
# already its own row, read from what the decide route queued.
CASE_ENTRY = {
    "opened": "Opened the case",
    "run": "Added a run",
    "chat": "Added a chat",
    "note": "Added a note",
    "field": "Changed its fields",
    "link": "Linked another case",
}
STATUSES = ("running", "waiting", "done", "failed", "skipped")
# The node types whose step calls the tool gateway: each attempt is one tool call.
TOOL_NODE_TYPES = tuple(t.id for t in default_registry().all() if t.executor == "gateway.call")
# A chat a person has not named yet; the chat list shows the same.
NEW_CHAT = "New chat"


@dataclass(frozen=True)
class Scope:
    """Where the caller may read each kind. `teams[kind]` None means every team (a dev caller); a kind missing reads
    nothing. A chat is read in `chat_all` teams whoever started it and in the others only when `owner` started it."""

    teams: dict[str, tuple[str, ...] | None]
    owner: str
    chat_all: tuple[str, ...] | None = ()


@dataclass(frozen=True)
class Filters:
    kinds: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    # (type, id) pairs: workflow, agent or channel.
    sources: tuple[tuple[str, str], ...] = ()
    since: str | None = None
    until: str | None = None
    # One case's entries and the rows about the runs and chats linked to it, in the case's team (c-341).
    case: tuple[str, str] | None = None  # (case id, its team)


@dataclass
class Page:
    rows: list[dict[str, Any]]
    total: int
    by_kind: dict[str, int] = field(default_factory=dict[str, int])
    by_status: dict[str, int] = field(default_factory=dict[str, int])


def _in_teams(column: sa.ColumnElement[Any], teams: tuple[str, ...] | None) -> sa.ColumnElement[bool]:
    return sa.true() if teams is None else column.in_(teams)


def _starter(r: sa.Table) -> sa.ColumnElement[Any]:
    """A run's actor as api/actors.py parses it: created_by, with ` via <event>` when an event carried the request."""
    return sa.case((r.c.started_via.is_not(None), r.c.created_by + " via " + r.c.started_via), else_=r.c.created_by)


def _workflow_runs(teams: tuple[str, ...] | None) -> sa.Select[*tuple[Any, ...]]:
    r, d = engine_runs, engine_definitions
    named = r.outerjoin(
        d, sa.and_(d.c.tenant_id == r.c.tenant_id, d.c.workflow_id == r.c.workflow_id, d.c.version == r.c.version)
    )
    name = sa.func.coalesce(d.c.name, r.c.workflow_id)
    status = sa.case(
        (r.c.status.in_(("queued", "running")), "running"),
        (r.c.status == "waiting", "waiting"),
        (r.c.status == "succeeded", "done"),
        else_="failed",
    )
    return (
        sa.select(
            sa.literal("workflow_run").label("kind"),
            r.c.id.label("row_id"),
            name.label("title"),
            status.label("status"),
            sa.func.coalesce(r.c.outcome, r.c.status).label("outcome"),
            r.c.team_id.label("team_id"),
            sa.literal("workflow").label("source_type"),
            r.c.workflow_id.label("source_id"),
            name.label("source_name"),
            _starter(r).label("actor"),
            r.c.created_at.label("at"),
            sa.literal("run").label("ref_kind"),
            r.c.id.label("ref_id"),
        )
        .select_from(named)
        .where(r.c.tenant_id == current_tenant(), _in_teams(r.c.team_id, teams))
    )


def _threads(kind: Kind, scope: Scope) -> sa.Select[*tuple[Any, ...]]:
    """Chats (a person's conversation with an agent) and agent runs (a thread started any other way). A child thread
    is part of its parent's row, not one of its own."""
    t = graph_threads
    meta = t.c.meta
    is_chat = meta["chat"].as_boolean().is_(True)
    shown = sa.or_(meta["hidden"].as_boolean().is_(None), meta["hidden"].as_boolean().is_(False))
    status = sa.case(
        (t.c.status.in_(("busy", "running", "route", "resume", "input")), "running"),
        (t.c.status == "interrupted", "waiting"),
        (t.c.status == "error", "failed"),
        else_="done",
    )
    agent_name = sa.func.coalesce(meta["agentName"].as_string(), t.c.graph)
    if kind == "chat":
        title = sa.func.coalesce(meta["title"].as_string(), NEW_CHAT)
        own = meta["ownerEmail"].as_string() == scope.owner
        if scope.chat_all is None:
            readable: sa.ColumnElement[bool] = sa.true()
        else:
            readable = sa.or_(t.c.team_id.in_(scope.chat_all), own)
        where = [is_chat, shown, readable]
    else:
        title = agent_name
        where = [sa.not_(sa.func.coalesce(is_chat, False)), t.c.parent_thread_id.is_(None)]
    # A chat started from an embedded widget belongs to that widget's channel; one in the console, to its agent.
    w = widget_deployments
    joined = t.outerjoin(w, sa.and_(w.c.tenant_id == t.c.tenant_id, w.c.id == t.c.deployment_id))
    from_widget = t.c.deployment_id.is_not(None)
    return (
        sa.select(
            sa.literal(kind).label("kind"),
            t.c.id.label("row_id"),
            title.label("title"),
            status.label("status"),
            t.c.status.label("outcome"),
            t.c.team_id.label("team_id"),
            sa.case((from_widget, "channel"), else_="agent").label("source_type"),
            sa.case(
                (from_widget, t.c.deployment_id), else_=sa.func.coalesce(meta["agentId"].as_string(), t.c.graph)
            ).label("source_id"),
            sa.case((from_widget, sa.func.coalesce(w.c.name, t.c.deployment_id)), else_=agent_name).label(
                "source_name"
            ),
            sa.func.coalesce(meta["ownerEmail"].as_string(), meta["owner"].as_string(), "").label("actor"),
            t.c.created_at.label("at"),
            sa.literal("chat" if kind == "chat" else "thread").label("ref_kind"),
            t.c.id.label("ref_id"),
        )
        .select_from(joined)
        .where(t.c.tenant_id == current_tenant(), _in_teams(t.c.team_id, scope.teams.get(kind)), *where)
    )


def _emails(teams: tuple[str, ...] | None) -> sa.Select[*tuple[Any, ...]]:
    """An email names its channel by the mailbox record's id and name; by its address when the record is gone."""
    e, m = trigger_events, mailboxes
    address = sa.func.substr(e.c.source, len("email:") + 1)
    joined = e.outerjoin(m, sa.and_(m.c.tenant_id == e.c.tenant_id, m.c.address == address))
    return (
        sa.select(
            sa.literal("email").label("kind"),
            e.c.id.label("row_id"),
            sa.func.coalesce(sa.func.nullif(e.c.subject, ""), "(no subject)").label("title"),
            sa.case((e.c.outcome == "started", "done"), else_="skipped").label("status"),
            e.c.outcome.label("outcome"),
            e.c.team_id.label("team_id"),
            sa.literal("channel").label("source_type"),
            sa.func.coalesce(m.c.id, address).label("source_id"),
            sa.func.coalesce(m.c.name, address).label("source_name"),
            e.c.sender.label("actor"),
            e.c.recorded_at.label("at"),
            sa.case((e.c.run_id.is_not(None), "run"), else_="email").label("ref_kind"),
            sa.func.coalesce(e.c.run_id, e.c.id).label("ref_id"),
        )
        .select_from(joined)
        .where(e.c.tenant_id == current_tenant(), _in_teams(e.c.team_id, teams))
    )


def _workflow_decisions(teams: tuple[str, ...] | None) -> sa.Select[*tuple[Any, ...]]:
    """A person's decision on a workflow's Human Task: the resume work row it queued for the run."""
    w, r, d = engine_work, engine_runs, engine_definitions
    joined = w.join(r, sa.and_(r.c.tenant_id == w.c.tenant_id, r.c.id == w.c.run_id)).outerjoin(
        d, sa.and_(d.c.tenant_id == r.c.tenant_id, d.c.workflow_id == r.c.workflow_id, d.c.version == r.c.version)
    )
    name = sa.func.coalesce(d.c.name, r.c.workflow_id)
    # decide() queues {"resume": {"decision", "by", ...}, "payload", "at", "interruptId"}.
    decision = w.c.payload[("resume", "decision")].as_string()
    return (
        sa.select(
            sa.literal("decision").label("kind"),
            sa.cast(w.c.id, sa.String).label("row_id"),
            name.label("title"),
            sa.literal("done").label("status"),
            decision.label("outcome"),
            r.c.team_id.label("team_id"),
            sa.literal("workflow").label("source_type"),
            r.c.workflow_id.label("source_id"),
            name.label("source_name"),
            sa.func.coalesce(w.c.payload[("resume", "by")].as_string(), "").label("actor"),
            w.c.created_at.label("at"),
            sa.literal("review").label("ref_kind"),
            r.c.id.label("ref_id"),
        )
        .select_from(joined)
        .where(
            w.c.tenant_id == current_tenant(),
            w.c.kind == "resume",
            decision.is_not(None),
            _in_teams(r.c.team_id, teams),
        )
    )


def _agent_decisions(teams: tuple[str, ...] | None) -> sa.Select[*tuple[Any, ...]]:
    """A person's decision on an agent's approval (a v1 review), on the thread that asked for it."""
    v, t = review_decisions, graph_threads
    joined = v.outerjoin(t, sa.and_(t.c.tenant_id == v.c.tenant_id, t.c.id == v.c.thread_id))
    agent = sa.func.coalesce(t.c.meta["agentName"].as_string(), t.c.graph, "")
    return (
        sa.select(
            sa.literal("decision").label("kind"),
            v.c.decision_id.label("row_id"),
            sa.func.coalesce(v.c.review["title"].as_string(), agent).label("title"),
            sa.literal("done").label("status"),
            v.c.decision.label("outcome"),
            v.c.team_id.label("team_id"),
            sa.literal("agent").label("source_type"),
            sa.func.coalesce(t.c.meta["agentId"].as_string(), t.c.graph, "").label("source_id"),
            agent.label("source_name"),
            v.c.decided_by.label("actor"),
            v.c.decided_at.label("at"),
            sa.literal("review").label("ref_kind"),
            v.c.thread_id.label("ref_id"),
        )
        .select_from(joined)
        .where(v.c.tenant_id == current_tenant(), _in_teams(v.c.team_id, teams))
    )


def _thread_tool_calls(scope: Scope) -> sa.Select[*tuple[Any, ...]]:
    """A tool an agent called in a chat or an agent run, from the thread's `tool_end` event. It is read where its
    thread is: a chat's under the chat rule, an agent run's where the caller views agents."""
    e, t, w = thread_events, graph_threads, widget_deployments
    joined = e.join(t, sa.and_(t.c.tenant_id == e.c.tenant_id, t.c.id == e.c.thread_id)).outerjoin(
        w, sa.and_(w.c.tenant_id == t.c.tenant_id, w.c.id == t.c.deployment_id)
    )
    meta = t.c.meta
    is_chat = sa.func.coalesce(meta["chat"].as_boolean(), False)
    own = meta["ownerEmail"].as_string() == scope.owner
    chat_teams, agent_teams = scope.teams.get("chat", ()), scope.teams.get("agent_run", ())
    chat_ok = sa.and_(
        _in_teams(t.c.team_id, chat_teams),
        sa.true() if scope.chat_all is None else sa.or_(t.c.team_id.in_(scope.chat_all), own),
    )
    visible = sa.or_(sa.and_(is_chat, chat_ok), sa.and_(sa.not_(is_chat), _in_teams(t.c.team_id, agent_teams)))
    status = e.c.data["status"].as_string()
    from_widget = t.c.deployment_id.is_not(None)
    agent_name = sa.func.coalesce(meta["agentName"].as_string(), t.c.graph)
    return (
        sa.select(
            sa.literal("tool_call").label("kind"),
            e.c.id.label("row_id"),
            sa.func.coalesce(e.c.data["tool"].as_string(), "tool").label("title"),
            sa.case(
                (status == "ok", "done"),
                (status == "gated", "waiting"),
                (status == "running", "running"),
                else_="failed",
            ).label("status"),
            status.label("outcome"),
            t.c.team_id.label("team_id"),
            sa.case((from_widget, "channel"), else_="agent").label("source_type"),
            sa.case(
                (from_widget, t.c.deployment_id), else_=sa.func.coalesce(meta["agentId"].as_string(), t.c.graph)
            ).label("source_id"),
            sa.case((from_widget, sa.func.coalesce(w.c.name, t.c.deployment_id)), else_=agent_name).label(
                "source_name"
            ),
            sa.func.coalesce(meta["ownerEmail"].as_string(), meta["owner"].as_string(), "").label("actor"),
            e.c.at.label("at"),
            sa.case((is_chat, "chat"), else_="thread").label("ref_kind"),
            t.c.id.label("ref_id"),
        )
        .select_from(joined)
        .where(e.c.tenant_id == current_tenant(), e.c.type == "tool_end", visible)
    )


def _workflow_tool_calls(teams: tuple[str, ...] | None) -> sa.Select[*tuple[Any, ...]]:
    """A tool a workflow's step called: one row per attempt, since each attempt reached the tool gateway."""
    s, r = engine_steps, engine_runs
    joined = s.join(r, sa.and_(r.c.tenant_id == s.c.tenant_id, r.c.id == s.c.run_id))
    status = sa.case(
        (s.c.status == "ok", "done"),
        (s.c.status.in_(("running", "pinned")), "running"),
        (s.c.status == "waiting", "waiting"),
        else_="failed",
    )
    return (
        sa.select(
            sa.literal("tool_call").label("kind"),
            sa.func.concat(s.c.run_id, ":", s.c.node_id, ":", s.c.iteration, ":", s.c.attempt).label("row_id"),
            sa.func.coalesce(s.c.input["operation"].as_string(), s.c.node_id).label("title"),
            status.label("status"),
            s.c.status.label("outcome"),
            r.c.team_id.label("team_id"),
            sa.literal("workflow").label("source_type"),
            r.c.workflow_id.label("source_id"),
            r.c.workflow_id.label("source_name"),
            _starter(r).label("actor"),
            s.c.started_at.label("at"),
            sa.literal("run").label("ref_kind"),
            r.c.id.label("ref_id"),
        )
        .select_from(joined)
        .where(s.c.tenant_id == current_tenant(), s.c.node_type.in_(TOOL_NODE_TYPES), _in_teams(r.c.team_id, teams))
    )


def _case_entries(teams: tuple[str, ...] | None) -> sa.Select[*tuple[Any, ...]]:
    """What was done on a case: opened, a run or chat added, a note, a field changed, a case linked."""
    e, k = case_events, cases
    joined = e.join(k, sa.and_(k.c.tenant_id == e.c.tenant_id, k.c.id == e.c.case_id))
    title = sa.case(*((e.c.kind == kind, text) for kind, text in CASE_ENTRY.items()), else_=e.c.kind)
    return (
        sa.select(
            sa.literal("case").label("kind"),
            e.c.id.label("row_id"),
            title.label("title"),
            sa.literal("done").label("status"),
            e.c.kind.label("outcome"),
            k.c.team_id.label("team_id"),
            sa.literal("case").label("source_type"),
            k.c.id.label("source_id"),
            k.c.subject.label("source_name"),
            e.c.by.label("actor"),
            e.c.at.label("at"),
            sa.literal("case").label("ref_kind"),
            k.c.id.label("ref_id"),
        )
        .select_from(joined)
        .where(e.c.tenant_id == current_tenant(), e.c.kind != "decision", _in_teams(k.c.team_id, teams))
    )


# The service events a shipped system workflow's change is recorded as (api/service_events.py, c-288).
SYSTEM_UPDATED = "system_workflow.updated"
SYSTEM_UPDATE_AVAILABLE = "system_workflow.update_available"


def _system_workflows(teams: tuple[str, ...] | None) -> sa.Select[*tuple[Any, ...]]:
    """A shipped system workflow moved to a new version, or one a person published differs from a newer shipped one.
    A system workflow belongs to no team, so a caller sees these where they may view workflows in any team asked
    about. An update's status is its publish request's now, not the one recorded when it was opened: a review decided
    later reads decided."""
    e, r, d = service_events, publish_requests, engine_definitions
    workflow_id = e.c.payload["workflowId"].as_string()
    review = sa.and_(r.c.tenant_id == e.c.tenant_id, r.c.id == e.c.payload["reviewId"].as_string())
    available = e.c.name == SYSTEM_UPDATE_AVAILABLE
    decided = sa.func.coalesce(r.c.status, e.c.payload["status"].as_string())
    waiting = sa.and_(sa.not_(available), decided.in_(("pending", "returned")))
    name = (
        sa.select(d.c.name)
        .where(d.c.tenant_id == e.c.tenant_id, d.c.workflow_id == workflow_id)
        .order_by(d.c.version.desc())
        .limit(1)
        .scalar_subquery()
    )
    return (
        sa.select(
            sa.literal("system_workflow").label("kind"),
            e.c.id.label("row_id"),
            sa.case(
                (available, "Shipped update available, own version kept"),
                (waiting, "Shipped update waiting for review"),
                (decided == "rejected", "Shipped update rejected"),
                else_="Updated to the shipped version",
            ).label("title"),
            sa.case((sa.or_(available, waiting), "waiting"), (decided == "rejected", "skipped"), else_="done").label(
                "status"
            ),
            sa.case((available, "update_available"), else_=decided).label("outcome"),
            sa.func.nullif(e.c.team_id, "").label("team_id"),
            sa.literal("workflow").label("source_type"),
            workflow_id.label("source_id"),
            sa.func.coalesce(name, workflow_id).label("source_name"),
            (sa.literal("event:") + e.c.source + "/" + e.c.name).label("actor"),
            e.c.recorded_at.label("at"),
            sa.case((waiting, "review"), else_="workflow").label("ref_kind"),
            sa.case((waiting, r.c.id), else_=workflow_id).label("ref_id"),
        )
        .select_from(e.outerjoin(r, review))
        .where(
            e.c.tenant_id == current_tenant(),
            e.c.name.in_((SYSTEM_UPDATED, SYSTEM_UPDATE_AVAILABLE)),
            sa.true() if teams is None or teams else sa.false(),
        )
    )


# A review still waiting was reminded (api/service_events.py reminders, c-277).
REMINDER = "task.reminder"


def _reminders(teams: tuple[str, ...] | None) -> sa.Select[*tuple[Any, ...]]:
    """Each reminder on a waiting review: the step's title and the hours it had waited, waiting while the run still
    waits and done once it has moved on, in the run's team."""
    e, r = service_events, engine_runs
    run_id = e.c.payload["runId"].as_string()
    workflow_id = e.c.payload["workflowId"].as_string()
    step = sa.func.coalesce(e.c.payload["title"].as_string(), e.c.payload["node"].as_string())
    name = (
        sa.select(engine_definitions.c.name)
        .where(engine_definitions.c.tenant_id == e.c.tenant_id, engine_definitions.c.workflow_id == workflow_id)
        .order_by(engine_definitions.c.version.desc())
        .limit(1)
        .scalar_subquery()
    )
    return (
        sa.select(
            sa.literal("reminder").label("kind"),
            e.c.id.label("row_id"),
            (sa.literal("Reminder: ") + step + ", waiting " + e.c.payload["waitedHours"].as_string() + " h").label(
                "title"
            ),
            sa.case((r.c.status == "waiting", "waiting"), else_="done").label("status"),
            sa.literal("reminded").label("outcome"),
            e.c.team_id.label("team_id"),
            sa.literal("workflow").label("source_type"),
            workflow_id.label("source_id"),
            sa.func.coalesce(name, workflow_id).label("source_name"),
            (sa.literal("event:") + e.c.source + "/" + e.c.name).label("actor"),
            e.c.recorded_at.label("at"),
            sa.literal("review").label("ref_kind"),
            run_id.label("ref_id"),
        )
        .select_from(e.outerjoin(r, sa.and_(r.c.tenant_id == e.c.tenant_id, r.c.id == run_id)))
        .where(e.c.tenant_id == current_tenant(), e.c.name == REMINDER, _in_teams(e.c.team_id, teams))
    )


def _on_case(a: sa.Subquery, case_id: str, team: str) -> sa.ColumnElement[bool]:
    """The case's own entries, and every row whose run or chat the case links, in the case's team only."""
    linked = sa.select(case_events.c.ref).where(
        case_events.c.tenant_id == current_tenant(),
        case_events.c.case_id == case_id,
        case_events.c.kind.in_(("run", "chat")),
        case_events.c.ref.is_not(None),
    )
    mine = sa.and_(a.c.kind == "case", a.c.source_id == case_id)
    return sa.and_(a.c.team_id == team, sa.or_(mine, sa.and_(a.c.kind != "case", a.c.ref_id.in_(linked))))


def union(scope: Scope) -> sa.Subquery:
    """Every kind the caller may read, as one subquery of the same columns."""
    parts: list[sa.Select[*tuple[Any, ...]]] = []
    if "workflow_run" in scope.teams:
        parts.append(_workflow_runs(scope.teams["workflow_run"]))
    for kind in ("agent_run", "chat"):
        if kind in scope.teams:
            parts.append(_threads(kind, scope))
    if "email" in scope.teams:
        parts.append(_emails(scope.teams["email"]))
    if "decision" in scope.teams:
        parts.append(_workflow_decisions(scope.teams["decision"]))
        parts.append(_agent_decisions(scope.teams["decision"]))
    if "tool_call" in scope.teams:
        parts.append(_thread_tool_calls(scope))
        parts.append(_workflow_tool_calls(scope.teams.get("workflow_run", ())))
    if "case" in scope.teams:
        parts.append(_case_entries(scope.teams["case"]))
    if "system_workflow" in scope.teams:
        parts.append(_system_workflows(scope.teams["system_workflow"]))
    if "reminder" in scope.teams:
        parts.append(_reminders(scope.teams["reminder"]))
    if not parts:
        parts.append(_workflow_runs(()))  # reads nothing, but keeps the query's shape
    return sa.union_all(*parts).subquery("activity")


class Activity:
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def page(self, scope: Scope, filters: Filters, *, page: int, page_size: int) -> Page:
        a = union(scope)
        common: list[sa.ColumnElement[bool]] = []
        if filters.sources:
            common.append(
                sa.or_(*(sa.and_(a.c.source_type == kind, a.c.source_id == sid) for kind, sid in filters.sources))
            )
        if filters.since:
            common.append(a.c.at >= filters.since)
        if filters.until:
            common.append(a.c.at < filters.until)
        if filters.case:
            common.append(_on_case(a, *filters.case))
        by_kind = a.c.kind.in_(filters.kinds) if filters.kinds else sa.true()
        by_status = a.c.status.in_(filters.statuses) if filters.statuses else sa.true()
        rows_q = (
            sa.select(a)
            .where(*common, by_kind, by_status)
            .order_by(a.c.at.desc(), a.c.kind, a.c.row_id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        total_q = sa.select(sa.func.count()).select_from(a).where(*common, by_kind, by_status)
        kinds_q = sa.select(a.c.kind, sa.func.count()).where(*common, by_status).group_by(a.c.kind)
        statuses_q = sa.select(a.c.status, sa.func.count()).where(*common, by_kind).group_by(a.c.status)
        async with tenant_tx(self.engine) as c:
            rows = [dict(r) for r in (await c.execute(rows_q)).mappings().all()]
            total = int((await c.execute(total_q)).scalar_one())
            kinds = {str(k): int(n) for k, n in (await c.execute(kinds_q)).all()}
            statuses = {str(s): int(n) for s, n in (await c.execute(statuses_q)).all()}
        return Page(rows, total, kinds, statuses)
