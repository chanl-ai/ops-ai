"""Where a registry or deployment row's tenant comes from while those tables carry none, as statements the migration
that adds the column and the operator preflight both run, so the preflight reports exactly what would stop the
migration (docs/architecture/migration/agents-registry-tenancy.md).

A row's tenant is, in order: a direct reference from a table that has a tenant; the one tenant its team is seen in
across the tables that hold both a team and a tenant; `local`. The preflight's gaps are the teams the second step
needs and cannot answer: a team seen in no tenant, and a team seen in two or more.

Tables and columns are named here as of agents revision 0105, not taken from the models, so a later model change does
not move what a shipped migration did.
"""

from __future__ import annotations

from typing import Any, Literal

import sqlalchemy as sa

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, backfill_ddl

CHAIN = "agents"

# The tables that hold both a team and a tenant, each team-isolated.
TEAM_TENANT_SOURCES = (
    "graph_threads",
    "graph_runs",
    "cases",
    "mailboxes",
    "team_default_agents",
    "template_copies",
    "widget_deployments",
    "eval_cases",
    "eval_runs",
    "form_links",
    "agent_memories",
    "review_decisions",
    "review_approvals",
)

Registry = Literal["agent", "guardrail", "skill", "widget", "workflow"]
REGISTRY_TABLES: dict[Registry, str] = {
    "agent": "registry_agents",
    "guardrail": "registry_guardrails",
    "skill": "registry_skills",
    "widget": "registry_widgets",
    "workflow": "registry_workflows",
}


def _table(name: str, *columns: str) -> sa.TableClause:
    return sa.table(name, *(sa.column(c, sa.String) for c in columns))


graph_threads = _table("graph_threads", "tenant_id", "team_id", "graph", "deployment_id")
template_copies = _table("template_copies", "tenant_id", "kind", "record_id")
team_default_agents = _table("team_default_agents", "tenant_id", "agent_id")
widget_deployments = _table("widget_deployments", "tenant_id", "agent_id")
publish_requests = _table("registry_publish_requests", "tenant_id", "kind", "subject_id")
deployments = _table("deployments", "id", "team_id")


def team_tenants() -> sa.Subquery:
    """Every distinct (team_id, tenant_id) pair the agents database holds; an empty team is no team."""
    selects = [
        sa.select(t.c.team_id, t.c.tenant_id).where(t.c.team_id != "")
        for t in (_table(name, "team_id", "tenant_id") for name in TEAM_TENANT_SOURCES)
    ]
    return sa.union(*selects).subquery("team_tenants")


def direct_tenants(kind: Registry) -> sa.CompoundSelect[Any, Any] | None:
    """(record_id, tenant_id) for each reference to a `kind` row from a table with a tenant; None when nothing names
    that kind. A thread names an agent as `agent:<id>` and a workflow by its id."""
    copies = sa.select(template_copies.c.record_id, template_copies.c.tenant_id).where(template_copies.c.kind == kind)
    match kind:
        case "agent":
            agents = _table("registry_agents", "id")
            return sa.union(
                copies,
                sa.select(team_default_agents.c.agent_id, team_default_agents.c.tenant_id),
                sa.select(widget_deployments.c.agent_id, widget_deployments.c.tenant_id),
                sa.select(publish_requests.c.subject_id, publish_requests.c.tenant_id).where(
                    publish_requests.c.kind == "agent"
                ),
                sa.select(agents.c.id, graph_threads.c.tenant_id).join_from(
                    agents, graph_threads, graph_threads.c.graph == sa.literal("agent:") + agents.c.id
                ),
            )
        case "workflow":
            return sa.union(
                copies,
                sa.select(publish_requests.c.subject_id, publish_requests.c.tenant_id).where(
                    publish_requests.c.kind == "workflow"
                ),
                sa.select(graph_threads.c.graph, graph_threads.c.tenant_id),
            )
        case "guardrail" | "skill":
            return sa.union(copies)
        case "widget":
            return None


def team_placed() -> sa.Subquery:
    """(source, team_id) for each registry or deployment row whose tenant only its team can give: no direct reference,
    and, for a deployment, no thread and a team that is not empty."""
    selects: list[sa.Select[str, Any]] = []
    for kind, name in REGISTRY_TABLES.items():
        t = _table(name, "id", "team_id")
        q = sa.select(sa.literal(name, sa.String).label("source"), t.c.team_id).where(t.c.team_id != "")
        direct = direct_tenants(kind)
        if direct is not None:
            refs = direct.subquery()
            q = q.where(t.c.id.not_in(sa.select(refs.c.record_id).where(refs.c.record_id.is_not(None))))
        selects.append(q)
    threaded = sa.select(graph_threads.c.deployment_id).where(graph_threads.c.deployment_id.is_not(None))
    selects.append(
        sa.select(sa.literal("deployments", sa.String).label("source"), deployments.c.team_id).where(
            deployments.c.team_id != "", deployments.c.id.not_in(threaded)
        )
    )
    return sa.union_all(*selects).subquery("team_placed")


def unmapped_teams() -> sa.Select[Any, Any, int]:
    """(team_id, source, rows) for the rows whose team is seen in no tenant."""
    placed, pairs = team_placed(), team_tenants()
    return (
        sa.select(placed.c.team_id, placed.c.source, sa.func.count().label("rows"))
        .where(placed.c.team_id.not_in(sa.select(pairs.c.team_id)))
        .group_by(placed.c.team_id, placed.c.source)
        .order_by(placed.c.team_id, placed.c.source)
    )


def two_tenant_teams() -> sa.Select[Any, Any]:
    """(team_id, tenant_id) for each team some row needs that is seen in two or more tenants."""
    placed, pairs = team_placed(), team_tenants()
    shared = sa.select(pairs.c.team_id).group_by(pairs.c.team_id).having(sa.func.count() > 1)
    return (
        sa.select(pairs.c.team_id, pairs.c.tenant_id)
        .where(pairs.c.team_id.in_(shared), pairs.c.team_id.in_(sa.select(placed.c.team_id)))
        .order_by(pairs.c.team_id, pairs.c.tenant_id)
    )


def _policed(name: str, kind: Literal["team", "tenant"]) -> sa.Table:
    info = {**TENANT_SCOPED, **TEAM_OWNED} if kind == "team" else TENANT_SCOPED
    columns = [sa.Column("tenant_id", sa.String(64))]
    if kind == "team":
        columns.append(sa.Column("team_id", sa.String(64)))
    return sa.Table(name, sa.MetaData(), *columns, info=info)


def every_tenant(dialect: str) -> tuple[list[str], list[str]]:
    """(before, after) a read or write of every tenant's rows of the tables above: row security off on PostgreSQL,
    each policy dropped and made again on SQL Server (`backfill_ddl`). A read that must change nothing runs `before`
    in a transaction it rolls back."""
    team_before, team_after = backfill_ddl(
        [_policed(n, "team") for n in TEAM_TENANT_SOURCES], dialect, chain=CHAIN, kind="team"
    )
    tenant_before, tenant_after = backfill_ddl(
        [_policed("registry_publish_requests", "tenant")], dialect, chain=CHAIN, kind="tenant"
    )
    if dialect == "postgresql":
        return team_before, team_after
    return team_before + tenant_before, team_after + tenant_after
