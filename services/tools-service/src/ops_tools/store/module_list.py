"""The Tools list (GET /v1/tool-modules) chosen, counted and paged in SQL.

Each module's view, state and figures are read from its rows in one statement: its operations (type, access, count),
approvals (state, next expiry), versions (an open review), the call log's last day (calls, errors) and the connection
it signs in with, which for a plugin's module is the acting team's binding (plugin_bindings.connection_id). The
connection's state follows `connections.records.status_of`, so a revoked, failing or expired account makes the module
unreachable as its page says. Only the page's modules are then read in full and shaped by the service.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, TypedDict

import sqlalchemy as sa

from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.listing import ListPage, list_page, listed_rows
from ops_store.store import Store
from ops_store.team_scope import team_visible

from .calls import RAN, gateway_calls
from .connections import connections
from .modules import (
    granted,
    module_approvals,
    module_operations,
    module_versions,
    seen_by,
    team_modules,
    tool_modules,
)
from .plugin_bindings import plugin_bindings
from .tenancy import ROLE

# A plugin's module is named by its template slot, plugin:<id> (plugins.host.TEMPLATE_PREFIX).
PLUGIN_SLOT = "plugin:"
# A connection in one of these is unreachable whatever its expiry; any but a draft is once its token expired.
DOWN = ("revoked", "error", "needs_reconnect")
VIEWS = ("needs_approval", "expiring", "expired", "failing", "security_review")


@dataclass(frozen=True)
class Window:
    """What the list's views are judged against: the service clock and its thresholds."""

    now: datetime
    expiring: timedelta
    failing_rate: float
    since: str  # the call log's created_at a day ago, in its text format
    call_teams: Sequence[str]  # whose calls count toward a module's traffic
    plugins: Sequence[str]  # installed plugins: a binding of any other signs nothing in


class Totals(TypedDict):
    """Over every module the team sees, unsearched and unfiltered: how many in all and in each view, and the sums."""

    all: int
    needs_approval: int
    expiring: int
    expired: int
    failing: int
    security_review: int
    operations: int
    calls: int
    errors: int
    expiring_approvals: int


def _flag(cond: sa.ColumnElement[bool]) -> sa.ColumnElement[int]:
    return sa.func.max(sa.case((cond, 1), else_=0))


def _count(cond: sa.ColumnElement[bool]) -> sa.ColumnElement[int]:
    return sa.func.sum(sa.case((cond, 1), else_=0))


def _derived(tenant_id: str, team_id: str, team: str | None, w: Window) -> sa.Subquery:
    """Every module the acting team (and `team`, when given) sees, one row each, with what the list filters, sorts
    and counts by. `team_id` is the team whose plugin bindings sign a plugin's module in."""
    t = tool_modules.c
    o = module_operations.c
    ops = (
        sa.select(
            o.module_id,
            sa.func.count().label("n"),
            _flag(o.access == "read").label("reads"),
            _flag(o.access == "write").label("writes"),
            _flag(o.executor == "mcp").label("mcp"),
            _flag(o.executor.in_(("code", "local"))).label("code"),
            _flag(o.executor == "http").label("http"),
        )
        .where(o.tenant_id == tenant_id)
        .group_by(o.module_id)
        .subquery("ops")
    )
    a = module_approvals.c
    approved = a.status == "approved"
    lapsed = sa.and_(approved, a.expires_at.is_not(None), a.expires_at < w.now)
    live = sa.and_(approved, sa.or_(a.expires_at.is_(None), a.expires_at >= w.now))
    apps = (
        sa.select(
            a.module_id,
            _count(a.status == "requested").label("pending"),
            _count(live).label("active"),
            _count(lapsed).label("lapsed"),
            sa.func.min(sa.case((live, a.expires_at))).label("next_expiry"),
            _count(sa.and_(live, a.expires_at < w.now + w.expiring)).label("expiring_approvals"),
        )
        .where(a.tenant_id == tenant_id)
        .group_by(a.module_id)
        .subquery("apps")
    )
    v = module_versions.c
    vers = (
        sa.select(
            v.module_id,
            _flag(v.status == "in_review").label("in_review"),
            _flag(sa.and_(v.status == "in_review", v.review_id.is_not(None))).label("waiting_review"),
            sa.func.max(v.position).label("last"),
        )
        .where(v.tenant_id == tenant_id)
        .group_by(v.module_id)
        .subquery("vers")
    )
    newest = module_versions.alias("newest")
    g = gateway_calls.c
    calls = (
        sa.select(g.module_id, sa.func.count().label("calls"), _count(g.outcome == "error").label("errors"))
        .where(
            g.tenant_id == tenant_id,
            g.team_id.in_(list(w.call_teams)),
            g.created_at >= w.since,
            g.outcome.in_(RAN),
        )
        .group_by(g.module_id)
        .subquery("calls")
    )
    b = plugin_bindings.c
    k = connections.c
    signs_in = sa.func.coalesce(t.connection_id, b.connection_id)
    joined = (
        tool_modules.outerjoin(ops, ops.c.module_id == t.id)
        .outerjoin(apps, apps.c.module_id == t.id)
        .outerjoin(vers, vers.c.module_id == t.id)
        .outerjoin(
            newest,
            sa.and_(newest.c.tenant_id == t.tenant_id, newest.c.module_id == t.id, newest.c.position == vers.c.last),
        )
        .outerjoin(calls, calls.c.module_id == t.id)
        .outerjoin(
            plugin_bindings,
            sa.and_(
                t.connection_id.is_(None),
                b.tenant_id == t.tenant_id,
                b.team_id == team_id,
                b.plugin_id.in_(list(w.plugins)),
                t.template_id == sa.literal(PLUGIN_SLOT) + b.plugin_id,
            ),
        )
        .outerjoin(connections, sa.and_(k.tenant_id == t.tenant_id, k.id == signs_in, team_visible(connections)))
    )
    pending = sa.func.coalesce(apps.c.pending, 0)
    review_open = sa.or_(
        vers.c.in_review == 1,
        sa.and_(newest.c.finding.is_not(None), newest.c.finding != "", newest.c.status.in_(("draft", "revoked"))),
    )
    state = sa.case(
        (t.status == "draft", "draft"),
        (sa.or_(t.status != "published", review_open, t.drift == sa.true(), pending > 0), "needs_approval"),
        (sa.and_(sa.func.coalesce(apps.c.active, 0) == 0, sa.func.coalesce(apps.c.lapsed, 0) > 0), "expired"),
        (apps.c.next_expiry < w.now + w.expiring, "expiring"),
        else_="approved",
    )
    down = sa.and_(k.id.is_not(None), sa.or_(k.status.in_(DOWN), sa.and_(k.status != "draft", k.expires_at < w.now)))
    n_calls = sa.func.coalesce(calls.c.calls, 0)
    n_errors = sa.func.coalesce(calls.c.errors, 0)
    as_float: sa.ColumnElement[float] = sa.cast(n_errors, sa.Float)
    rate = as_float / n_calls
    kind = sa.case(
        (ops.c.mcp == 1, "mcp"),
        (sa.and_(ops.c.code == 1, sa.func.coalesce(ops.c.http, 0) == 0), "code"),
        else_="http",
    )
    return (
        sa.select(
            t.tenant_id,
            t.id,
            signs_in.label("connection_id"),
            kind.label("type"),
            state.label("state"),
            apps.c.next_expiry,
            sa.func.coalesce(apps.c.expiring_approvals, 0).label("expiring_approvals"),
            sa.func.coalesce(vers.c.waiting_review, 0).label("waiting_review"),
            sa.func.coalesce(ops.c.n, 0).label("operations"),
            sa.func.coalesce(ops.c.reads, 0).label("reads"),
            sa.func.coalesce(ops.c.writes, 0).label("writes"),
            n_calls.label("calls"),
            n_errors.label("errors"),
            sa.case((n_calls > 0, rate), else_=0.0).label("error_rate"),
            sa.case((sa.and_(t.reachable == sa.true(), sa.not_(down)), 1), else_=0).label("reachable"),
        )
        .select_from(joined)
        .where(
            t.tenant_id == tenant_id,
            sa.or_(team_modules(), granted(tenant_id)),
            seen_by(tenant_id, team) if team is not None else sa.true(),
        )
        .subquery("d")
    )


def _views(d: sa.Subquery, w: Window) -> dict[str, sa.ColumnElement[bool]]:
    c = d.c
    return {
        "needs_approval": c.state.in_(("needs_approval", "draft")),
        "expiring": sa.and_(c.state != "expired", c.next_expiry < w.now + w.expiring),
        "expired": c.state == "expired",
        "failing": sa.or_(sa.and_(c.calls > 0, c.errors >= c.calls * w.failing_rate), c.reachable == 0),
        "security_review": c.waiting_review == 1,
    }


class ModuleList(Store):
    requires: ClassVar[frozenset[Guarantee]] = frozenset()
    role = ROLE

    async def page(
        self, tenant_id: str, team_id: str, q: ListParams, *, view: str, w: Window, seen_by: str | None
    ) -> tuple[ListPage, Totals]:
        """One page of `view` (`all` or one of VIEWS) with each row's id and the connection it signs in with; and the
        access facet, every view's count and the totals over every module seen, unsearched and unfiltered. `seen_by`:
        the caller's team, which the list names whatever scope the request reads in; None only for a caller that reads
        every team's."""
        d = _derived(tenant_id, team_id, seen_by, w)
        t = tool_modules.c
        views = _views(d, w)
        joined = tool_modules.join(d, sa.and_(d.c.tenant_id == t.tenant_id, d.c.id == t.id))
        seen = sa.or_(team_modules(), granted(tenant_id))
        base = sa.select(t.id, d.c.connection_id).select_from(joined).where(seen)
        in_view = base.where(views[view]) if view != "all" else base
        wanted = set(q.filters.get("access") or [])
        access = [d.c.reads == 1] * ("read" in wanted) + [d.c.writes == 1] * ("write" in wanted)
        listed = in_view.where(sa.or_(sa.false(), *access)) if wanted else in_view
        search = [t.display_name, t.name, t.system, t.description, t.owner_team]
        filters = {"type": d.c.type, "approvalState": d.c.state, "templateId": t.template_id}
        sortable = {
            "displayName": t.display_name,
            "name": t.name,
            "updatedAt": t.updated_at,
            "ownerTeam": t.owner_team,
            "calls24h": d.c.calls,
            "errorRate": d.c.error_rate,
            "operationCount": d.c.operations,
        }
        counts = [_count(where).label(name) for name, where in views.items()]
        # The access facet counts the rows shown under every filter but its own, in the same statement as the totals.
        shown = listed_rows(sa.select(t.id).select_from(joined), q, search=search, filters=filters).whereclause
        faceted = sa.and_(views[view] if view != "all" else sa.true(), shown if shown is not None else sa.true())
        totals = sa.select(
            sa.func.count().label("all"),
            *counts,
            sa.func.sum(d.c.operations).label("operations"),
            sa.func.sum(d.c.calls).label("calls"),
            sa.func.sum(d.c.errors).label("errors"),
            sa.func.sum(d.c.expiring_approvals).label("expiring_approvals"),
            sa.func.sum(sa.case((faceted, d.c.reads), else_=0)).label("reads"),
            sa.func.sum(sa.case((faceted, d.c.writes), else_=0)).label("writes"),
        ).select_from(joined)
        async with self.tx() as c:
            page = await list_page(
                c,
                listed,
                q,
                search=search,
                sortable=sortable,
                default_sort=t.created_at.desc(),
                filters=filters,
                facets={"type": d.c.type, "approvalState": d.c.state},
            )
            row = (await c.execute(totals)).mappings().one()
        page["facets"]["access"] = {k: int(row[f"{k}s"]) for k in ("read", "write") if row[f"{k}s"]}
        n = {k: int(row[k] or 0) for k in Totals.__annotations__}
        totals = Totals(
            all=n["all"],
            needs_approval=n["needs_approval"],
            expiring=n["expiring"],
            expired=n["expired"],
            failing=n["failing"],
            security_review=n["security_review"],
            operations=n["operations"],
            calls=n["calls"],
            errors=n["errors"],
            expiring_approvals=n["expiring_approvals"],
        )
        return page, totals
