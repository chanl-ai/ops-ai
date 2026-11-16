"""The v2 workflows list (`GET /v1/workflows/definitions`) a page at a time in SQL: each workflow at its latest
version, with its status worked out in the statement from the serving version's stage and its open publish request,
so the total, the status counts and the page come from the database. Here rather than in `ops_engine` because the
status reads agents' publish requests. `definition_columns` is the same select for the Workflows list, which joins
both engines' workflows."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from ops_engine.store.tables import engine_definitions, engine_runs
from ops_service_kit.listing import ListParams
from ops_store.listing import ListPage, list_page
from ops_store.team_scope import acting_team

from .agent_registry import publish_requests
from .tenancy import current_tenant, tenant_tx

# The publish request kind of a v2 workflow (`api.engine_lifecycle.KIND`).
ENGINE_KIND = "engine"
# The statuses a list shows unless `status` asks for others; an archived workflow is counted, not shown.
SHOWN = ("draft", "in_review", "live", "paused")
# The stages of the version that serves a workflow; at most one version is in one of them.
SERVING = ("live", "paused")


def _word(word: str) -> sa.ColumnClause[str]:
    """A fixed word written into the statement, not bound, so the status CASE is one expression wherever it is named
    (a GROUP BY and its select must match, and two bound copies are two parameters to SQL Server)."""
    return sa.literal_column(f"'{word}'", sa.String())


def definition_columns(*, since: str | None = None) -> tuple[sa.Select[Any], dict[str, sa.ColumnElement[Any]]]:
    """The tenant's v2 workflows the acting team may see (its own and the unowned ones; every one with no acting
    team), one row each at its latest version, and the list's columns by name: `status` is archived once archived,
    else the serving version's stage (live or paused), else in_review while a publish request is pending, else draft;
    `runs` counts its runs on every version and `recent` those started at or after `since`."""
    t, r, p = engine_definitions, engine_runs, publish_requests
    tenant = current_tenant()
    team = acting_team()
    newer = engine_definitions.alias("newer")
    seen: list[sa.ColumnElement[bool]] = [t.c.tenant_id == tenant]
    # The newest version the team may see, as each version carries its own team.
    later: list[sa.ColumnElement[bool]] = [
        newer.c.tenant_id == t.c.tenant_id,
        newer.c.workflow_id == t.c.workflow_id,
        newer.c.version > t.c.version,
    ]
    if team is not None:
        seen.append(sa.or_(t.c.team_id == team, t.c.team_id.is_(None)))
        later.append(sa.or_(newer.c.team_id == team, newer.c.team_id.is_(None)))
    latest = ~sa.exists().where(*later)
    serving = (
        sa.select(
            t.c.workflow_id,
            sa.func.max(t.c.version).label("live_version"),
            sa.func.max(t.c.stage).label("stage"),
        )
        .where(t.c.tenant_id == tenant, t.c.stage.in_(SERVING))
        .group_by(t.c.workflow_id)
        .subquery("serving")
    )
    recent: sa.ColumnElement[int] = (
        sa.case((r.c.created_at >= since, 1), else_=0) if since else sa.literal_column("0", sa.Integer())
    )
    counted = (
        sa.select(r.c.workflow_id, sa.func.count().label("runs"), sa.func.sum(recent).label("recent"))
        .where(r.c.tenant_id == tenant)
        .group_by(r.c.workflow_id)
        .subquery("counted")
    )
    pending = sa.exists().where(
        p.c.tenant_id == t.c.tenant_id,
        p.c.subject_id == t.c.workflow_id,
        p.c.kind == ENGINE_KIND,
        p.c.status == "pending",
    )
    status = sa.case(
        (t.c.archived_at.is_not(None), _word("archived")),
        (serving.c.stage.is_not(None), serving.c.stage),
        (pending, _word("in_review")),
        else_=_word("draft"),
    )
    runs = sa.func.coalesce(counted.c.runs, 0)
    columns: dict[str, sa.ColumnElement[Any]] = {
        "workflow_id": t.c.workflow_id,
        "name": t.c.name,
        "version": t.c.version,
        "digest": t.c.digest,
        "status": status,
        "live_version": serving.c.live_version,
        "runs": runs,
        "recent": sa.func.coalesce(counted.c.recent, 0),
        "updated_at": t.c.created_at,
        "updated_by": t.c.created_by,
    }
    q = (
        sa.select(*(c.label(name) for name, c in columns.items()))
        .select_from(
            t.outerjoin(serving, serving.c.workflow_id == t.c.workflow_id).outerjoin(
                counted, counted.c.workflow_id == t.c.workflow_id
            )
        )
        .where(*seen, latest)
    )
    return q, columns


def shown_unless_asked(params: ListParams) -> ListParams:
    """`params` with the status filter set to every status but archived when none is asked for: an archived workflow
    leaves the page, and the status facet, which leaves its own filter out, still counts it."""
    if params.filters.get("status"):
        return params
    return params.model_copy(update={"filters": {**params.filters, "status": list(SHOWN)}})


async def definitions_page(engine: Any, params: ListParams) -> ListPage:
    """The v2 workflows list on the shared contract: search over name and id, `status` filters (archived only when
    asked for), `facets.status` counts under the search, sorted by `sortBy` (name, updatedAt, runs, status, version;
    newest version first by default), then by the key. `ids` names workflows by id."""
    q, col = definition_columns()
    if params.ids is not None:
        # The table's key is (tenant, workflow, version), so `ids` names the workflow column here.
        q = q.where(engine_definitions.c.workflow_id.in_(params.ids))
        params = params.model_copy(update={"ids": None, "search": None})
    async with tenant_tx(engine) as c:
        return await list_page(
            c,
            q,
            shown_unless_asked(params),
            search=[col["name"], col["workflow_id"]],
            sortable={
                "name": col["name"],
                "updatedAt": col["updated_at"],
                "runs": col["runs"],
                "status": col["status"],
                "version": col["version"],
            },
            default_sort=col["updated_at"].desc(),
            filters={"status": col["status"]},
            facets={"status": col["status"]},
        )


__all__ = ["ENGINE_KIND", "SHOWN", "definition_columns", "definitions_page", "shown_unless_asked"]
