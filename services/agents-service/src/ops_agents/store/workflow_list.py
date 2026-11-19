"""The Workflows list (`GET /v1/workflows`) a page at a time in SQL: one UNION ALL of the registry's (v1) workflows and
the runner's (v2) workflows at their latest version, so the search, the filters, the status counts, the total, the sort
and the page all come from the database, and only the page's rows are read further (`page_details`). Each branch
carries its own tenant and team terms: v1 here, v2 in `definition_columns`."""

from __future__ import annotations

import sqlalchemy as sa
from pydantic import BaseModel, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_engine.store.definitions import HUMAN_REVIEW
from ops_engine.store.tables import engine_definitions, engine_runs, engine_steps
from ops_service_kit.listing import ListParams
from ops_store.listing import ListPage, list_page
from ops_store.team_scope import team_visible

from .agent_registry import publish_requests
from .definition_list import ENGINE_KIND, definition_columns, shown_unless_asked
from .graphs import graph_threads, mine
from .tenancy import current_tenant
from .workflow_registry import registry_workflow_versions, registry_workflows

# The publish request kind of a v1 workflow.
WORKFLOW_KIND = "workflow"
# What `sortBy` may name, by its query key.
SORTS = ("name", "updatedAt", "runs24h", "status", "version")


def workflow_sources(*, since: str, current_only: bool) -> sa.Subquery:
    """Both engines' workflows the acting team may see, one row each with the list's columns: the source (v1 or v2),
    id, name, description, team, trigger text, status, version (the published or serving one, 0 before it), last
    update, runs started at or after `since`, and whether a person starts it by hand and with a file. A v1 workflow
    starts from its input form, with no file field. `current_only` leaves the v1 workflows out."""
    w, th = registry_workflows, graph_threads
    recent = (
        sa.select(th.c.graph, sa.func.count().label("runs"))
        .where(mine(th), team_visible(th), th.c.created_at >= since)
        .group_by(th.c.graph)
        .subquery("recent_threads")
    )
    v1 = (
        sa.select(
            sa.literal_column("'v1'", sa.String()).label("source"),
            w.c.id.label("id"),
            w.c.name.label("name"),
            w.c.description.label("description"),
            w.c.team_id.label("team_id"),
            sa.cast(w.c.trigger, sa.Text()).label("trigger"),
            w.c.status.label("status"),
            sa.func.coalesce(w.c.published_version, 0).label("version"),
            w.c.updated_at.label("updated_at"),
            sa.func.coalesce(recent.c.runs, 0).label("runs24h"),
            sa.cast(sa.true(), sa.Boolean()).label("startable"),
            sa.cast(sa.false(), sa.Boolean()).label("takes_files"),
        )
        .select_from(w.outerjoin(recent, recent.c.graph == w.c.id))
        .where(mine(w), team_visible(w), w.c.status != "deleted")
    )
    q, col = definition_columns(since=since)
    t = engine_definitions
    v2 = q.with_only_columns(
        sa.literal_column("'v2'", sa.String()).label("source"),
        col["workflow_id"].label("id"),
        col["name"].label("name"),
        t.c.description.label("description"),
        t.c.team_id.label("team_id"),
        t.c.trigger.label("trigger"),
        col["status"].label("status"),
        sa.func.coalesce(col["live_version"], 0).label("version"),
        col["updated_at"].label("updated_at"),
        col["recent"].label("runs24h"),
        t.c.startable.label("startable"),
        t.c.takes_files.label("takes_files"),
        maintain_column_froms=True,
    )
    if current_only:
        return v2.subquery("workflows")
    return sa.union_all(v1, v2).subquery("workflows")


async def workflows_page(
    conn: AsyncConnection,
    params: ListParams,
    *,
    since: str,
    current_only: bool = False,
    startable: bool = False,
    takes_files: bool = False,
) -> ListPage:
    """The Workflows list on the shared contract: search over name and description, `status` filters (archived only
    when asked for) with `facets.status` counting under the search and the start filters, `startable` and
    `takes_files` keeping those a person starts by hand and with a file, sorted by `sortBy` (SORTS) then by source and
    id."""
    u = workflow_sources(since=since, current_only=current_only)
    query = sa.select(u)
    if startable:
        query = query.where(u.c.startable == sa.true())
    if takes_files:
        query = query.where(u.c.takes_files == sa.true())
    columns = {"name": u.c.name, "updatedAt": u.c.updated_at, "runs24h": u.c.runs24h}
    return await list_page(
        conn,
        query,
        shown_unless_asked(params),
        search=[u.c.name, u.c.description],
        sortable={**columns, "status": u.c.status, "version": u.c.version},
        default_sort=u.c.name,
        filters={"status": u.c.status},
        facets={"status": u.c.status},
        key=(u.c.source, u.c.id),
    )


class WorkflowRow(BaseModel):
    """A row of `workflow_sources`."""

    source: str
    id: str
    name: str
    description: str
    team_id: str | None
    trigger: str
    status: str
    version: int
    updated_at: str
    runs24h: int
    startable: bool
    takes_files: bool


class PendingPublish(BaseModel):
    """A workflow's open publish request."""

    id: str
    version: int
    requested_by: str


class PageExtra(BaseModel):
    """What `page_details` reads for one row of a page."""

    graph: JsonValue = None
    draft: JsonValue = None
    waiting: int = 0
    definition: JsonValue = None
    reviewed: int = 0
    open_reviews: int = 0
    pending: PendingPublish | None = None


async def page_details(
    conn: AsyncConnection, v1_ids: list[str], v2_ids: list[str], *, since: str
) -> dict[tuple[str, str], PageExtra]:
    """What a page's rows show beyond the list's columns, by (source, id), read for those rows only in the same
    statements whatever the page size: a v1 workflow's graph (its published version's, else its draft) and threads
    waiting on a person; a v2 workflow's latest definition, Human Tasks reached since `since` and open now; each one's
    open publish request."""
    out = {("v1", i): PageExtra() for i in v1_ids} | {("v2", i): PageExtra() for i in v2_ids}
    if v1_ids:
        w, v, th = registry_workflows, registry_workflow_versions, graph_threads
        live = sa.and_(v.c.tenant_id == w.c.tenant_id, v.c.workflow_id == w.c.id, v.c.version == w.c.published_version)
        q = (
            sa.select(w.c.id, w.c.draft, v.c.graph)
            .select_from(w.outerjoin(v, live))
            .where(mine(w), team_visible(w), w.c.id.in_(v1_ids))
        )
        for r in await conn.execute(q):
            out["v1", r.id] = out["v1", r.id].model_copy(update={"graph": r.graph, "draft": r.draft})
        waiting = (
            sa.select(th.c.graph, sa.func.count())
            .where(mine(th), team_visible(th), th.c.status == "interrupted", th.c.graph.in_(v1_ids))
            .group_by(th.c.graph)
        )
        for graph, n in await conn.execute(waiting):
            out["v1", graph].waiting = int(n)
    if v2_ids:
        t, r, s = engine_definitions, engine_runs, engine_steps
        q, col = definition_columns()
        defs = q.with_only_columns(col["workflow_id"], t.c.definition, maintain_column_froms=True).where(
            col["workflow_id"].in_(v2_ids)
        )
        for wid, definition in await conn.execute(defs):
            out["v2", wid].definition = definition
        reached = sa.case((r.c.created_at >= since, r.c.id))
        is_open = sa.and_(s.c.status == "waiting", r.c.status == "waiting")
        humans = (
            sa.select(
                r.c.workflow_id,
                sa.func.count(sa.distinct(reached)),
                sa.func.sum(sa.case((is_open, 1), else_=0)),
            )
            .join(s, sa.and_(s.c.run_id == r.c.id, s.c.tenant_id == r.c.tenant_id))
            .where(
                r.c.tenant_id == current_tenant(),
                r.c.workflow_id.in_(v2_ids),
                s.c.node_type == HUMAN_REVIEW,
                s.c.status != "error",
            )
            .group_by(r.c.workflow_id)
        )
        for wid, reviewed, open_now in await conn.execute(humans):
            out["v2", wid].reviewed, out["v2", wid].open_reviews = int(reviewed or 0), int(open_now or 0)
    p = publish_requests
    pending = (
        sa.select(p.c.kind, p.c.subject_id, p.c.id, p.c.version, p.c.requested_by)
        .where(
            p.c.tenant_id == current_tenant(),
            p.c.status == "pending",
            sa.or_(
                sa.and_(p.c.kind == WORKFLOW_KIND, p.c.subject_id.in_(v1_ids or [""])),
                sa.and_(p.c.kind == ENGINE_KIND, p.c.subject_id.in_(v2_ids or [""])),
            ),
        )
        .order_by(p.c.created_at.desc(), p.c.id)
    )
    for row in (await conn.execute(pending)).mappings():
        source = "v1" if row["kind"] == WORKFLOW_KIND else "v2"
        extra = out[source, str(row["subject_id"])]
        extra.pending = extra.pending or PendingPublish.model_validate(dict(row))
    return out


__all__ = ["SORTS", "PageExtra", "PendingPublish", "WorkflowRow", "page_details", "workflow_sources", "workflows_page"]
