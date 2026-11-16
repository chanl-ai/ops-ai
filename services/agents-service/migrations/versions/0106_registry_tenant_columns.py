"""The registry, graph version and channel tables carry their tenant

Revision ID: 0106_registry_tenant_columns
Revises: 0105_thread_owner_column

The agent, guardrail, skill, widget and workflow registries, their versions, workflow validations, graph_versions,
deployments and the channel tables had no tenant column, so nothing in the database could hold one tenant's rows from
another's (docs/architecture/migration/agents-registry-tenancy.md). Each gains `tenant_id` NOT NULL DEFAULT 'local',
filled by the precedence in ops_agents.store.registry_tenants: a direct reference from a table with a tenant, then the
one tenant the row's team is seen in, then 'local'; versions and validations take their parent's, graph_versions its
workflow's, the channel tables their thread's or deployment's. A deployment with no team takes its threads' team when
they share one. Publish requests gain `team_id`, their subject's team.

Outside dev the upgrade stops, before it changes a row, on a team seen in no tenant, a team or a record seen in two or
more tenants other than 'local' (`make -C services/agents-service registry-tenant-preflight` lists the same on
PostgreSQL); in dev each of those falls to 'local'. Offline SQL cannot check first: a team or record with two tenants
writes NULL into the NOT NULL column and the statement fails, and an unmapped team's rows take 'local'.

Keys: an agent's slug is unique per tenant; graph_versions is keyed (tenant_id, name, version) and its digest is unique
per tenant. Guardrails and skills gain a tenant-leading index. The keys whose current form the stores still name in
their upserts or foreign keys (widgets, workflows, deployments, channel messages and cursors) change with the stores,
as do the row policies, so every table stays on the markings waiting list. The tenant role gains the stores' grants on
PostgreSQL (SQL Server's runtime user holds them already). channel_files, which nothing reads or writes, is dropped.

The down path refuses, with a count, when a slug, a graph version or a digest is held by two tenants, since the
install-wide keys would fail partway; offline SQL cannot count. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

from ops_agents.store.registry_tenants import (
    LOCAL,
    TABLES,
    TEAM_TENANT_SOURCES,
    gaps_of,
    shared_records,
    shared_teams,
    table,
    tenant_of,
    unmapped_teams,
)
from ops_service_kit.settings import Settings
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, backfill_ddl

revision = "0106_registry_tenant_columns"
down_revision = "0105_thread_owner_column"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
# Each version table and validations, with the parent whose tenant it takes and the column that names the parent.
CHILDREN = {
    "registry_agent_versions": ("registry_agents", "agent_id"),
    "registry_guardrail_versions": ("registry_guardrails", "guardrail_id"),
    "registry_skill_versions": ("registry_skills", "skill_id"),
    "registry_widget_versions": ("registry_widgets", "widget_id"),
    "registry_workflow_versions": ("registry_workflows", "workflow_id"),
    "registry_validations": ("registry_workflows", "workflow_id"),
}
CHANNELS = ("channel_messages", "channel_cursors", "thread_inbox")
TENANTED = (*TABLES.values(), *CHILDREN, "graph_versions", *CHANNELS)
INDEXES = {
    "registry_guardrails": "ix_registry_guardrails_tenant_team",
    "registry_skills": "ix_registry_skills_tenant_team",
}
REQUESTS = "registry_publish_requests"
REQUESTS_TEAM = "ix_registry_publish_requests_team"
AGENT_SLUG = "uq_registry_agents_tenant_slug"
VERSION_DIGEST = "uq_graph_versions_tenant_digest"
VERSIONS_PK = "graph_versions_pkey"


def _policed(name: str, *, team: bool) -> sa.Table:
    """A source table as far as its policy needs, as of this revision."""
    columns = [sa.Column("tenant_id", sa.String(64)), *([sa.Column("team_id", sa.String(64))] if team else [])]
    return sa.Table(name, sa.MetaData(), *columns, info={**TENANT_SCOPED, **TEAM_OWNED} if team else TENANT_SCOPED)


def _every_tenant(dialect: str) -> tuple[list[str], list[str]]:
    """(before, after) reading and writing every tenant's rows of the policed tables the backfill touches."""
    teams = backfill_ddl([_policed(n, team=True) for n in TEAM_TENANT_SOURCES], dialect, chain=CHAIN, kind="team")
    if dialect != "mssql":
        return teams
    requests = backfill_ddl([_policed(REQUESTS, team=False)], dialect, chain=CHAIN, kind="tenant")
    return teams[0] + requests[0], teams[1] + requests[1]


def _drop_key(name: str, *, kind: str, column: str | None, pg_name: str) -> None:
    """Drops a primary (PK) or unique (UQ) key made inline: SQL Server generated its name, so it is found by its type
    and, for a unique key, its column. Plain SQL, so the revision also renders as offline SQL."""
    if op.get_bind().dialect.name == "mssql":
        by_column = (
            "JOIN sys.index_columns ic ON ic.object_id = k.parent_object_id AND ic.index_id = k.unique_index_id "
            "JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id "
            if column
            else ""
        )
        where = f" AND c.name = N'{column}'" if column else ""
        op.execute(
            f"DECLARE @n sysname = (SELECT k.name FROM sys.key_constraints k {by_column}"
            f"WHERE k.type = '{kind}' AND k.parent_object_id = OBJECT_ID(N'{name}'){where}); "
            f"IF @n IS NOT NULL EXEC (N'ALTER TABLE {name} DROP CONSTRAINT ' + QUOTENAME(@n))"
        )
    else:
        op.execute(f"ALTER TABLE {name} DROP CONSTRAINT IF EXISTS {pg_name}")


def _refuse_gaps() -> None:
    bind = op.get_bind()
    found = gaps_of((bind.execute(unmapped_teams()), bind.execute(shared_teams()), bind.execute(shared_records())))
    if lines := found.lines():
        raise RuntimeError(
            "0106: these registry or deployment rows have no one tenant to take; give each team and record one "
            "tenant, then migrate again:\n" + "\n".join(lines)
        )


def _backfill(dev: bool) -> None:
    deployments = table("deployments", "id", "team_id")
    threads = table("graph_threads", "tenant_id", "team_id", "deployment_id", "id")
    of_deployment = threads.c.deployment_id == deployments.c.id
    teams = sa.select(sa.func.count(sa.distinct(threads.c.team_id))).where(of_deployment, threads.c.team_id != "")
    op.execute(
        sa.update(deployments)
        .where(deployments.c.team_id == "", teams.scalar_subquery() == 1)
        .values(
            team_id=sa.select(sa.func.max(threads.c.team_id))
            .where(of_deployment, threads.c.team_id != "")
            .scalar_subquery()
        )
    )
    for kind, name in TABLES.items():
        row = table(name, "id", "team_id", "tenant_id")
        op.execute(sa.update(row).values(tenant_id=tenant_of(kind, row, dev=dev)))
    for name, (parent_name, key) in CHILDREN.items():
        child, parent = table(name, key, "tenant_id"), table(parent_name, "id", "tenant_id")
        found = sa.select(parent.c.tenant_id).where(parent.c.id == child.c[key])
        op.execute(sa.update(child).where(sa.exists(found)).values(tenant_id=found.scalar_subquery()))
    versions, workflows = table("graph_versions", "name", "tenant_id"), table("registry_workflows", "id", "tenant_id")
    found = sa.select(workflows.c.tenant_id).where(workflows.c.id == versions.c.name)
    op.execute(sa.update(versions).where(sa.exists(found)).values(tenant_id=found.scalar_subquery()))
    placed = table("deployments", "id", "tenant_id")
    for name in CHANNELS:
        row = table(name, *(("thread_id",) if name != "channel_cursors" else ()), "deployment_id", "tenant_id")
        cases: list[tuple[sa.ColumnElement[bool], sa.ColumnElement[Any]]] = []
        if "thread_id" in row.c:
            thread = sa.select(threads.c.tenant_id).where(threads.c.id == row.c.thread_id)
            cases.append((sa.exists(thread), thread.scalar_subquery()))
        if "deployment_id" in row.c and name != "thread_inbox":
            deployment = sa.select(placed.c.tenant_id).where(placed.c.id == row.c.deployment_id)
            cases.append((sa.exists(deployment), deployment.scalar_subquery()))
        op.execute(sa.update(row).values(tenant_id=sa.case(*cases, else_=LOCAL)))
    requests = table(REQUESTS, "kind", "subject_id", "team_id")
    for kind, name in TABLES.items():
        subject = table(name, "id", "team_id")
        team = sa.select(subject.c.team_id).where(subject.c.id == requests.c.subject_id)
        op.execute(
            sa.update(requests).where(requests.c.kind == kind, sa.exists(team)).values(team_id=team.scalar_subquery())
        )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    offline = op.get_context().as_sql
    # Offline SQL is a DBA script for a real install, never dev: it takes the outside-dev rules.
    dev = not offline and Settings().environment == "dev"
    for name in TENANTED:
        with op.batch_alter_table(name) as b:
            b.add_column(sa.Column("tenant_id", sa.String(64), nullable=False, server_default=LOCAL))
    with op.batch_alter_table(REQUESTS) as b:
        b.add_column(sa.Column("team_id", sa.String(64), nullable=False, server_default=""))
    before, after = _every_tenant(dialect)
    for statement in before:
        op.execute(statement)
    if not dev and not offline:
        _refuse_gaps()
    _backfill(dev)
    for statement in after:
        op.execute(statement)

    _drop_key("registry_agents", kind="UQ", column="slug", pg_name="registry_agents_slug_key")
    op.create_unique_constraint(AGENT_SLUG, "registry_agents", ["tenant_id", "slug"])
    _drop_key("graph_versions", kind="UQ", column="digest", pg_name="graph_versions_digest_key")
    _drop_key("graph_versions", kind="PK", column=None, pg_name=VERSIONS_PK)
    op.create_primary_key(VERSIONS_PK, "graph_versions", ["tenant_id", "name", "version"])
    op.create_unique_constraint(VERSION_DIGEST, "graph_versions", ["tenant_id", "digest"])
    for name, index in INDEXES.items():
        op.create_index(index, name, ["tenant_id", "team_id"])
    op.create_index(REQUESTS_TEAM, REQUESTS, ["tenant_id", "team_id"])
    if dialect == "postgresql":
        for name in TENANTED:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {TENANT_ROLE}")
    op.drop_table("channel_files")


def _refuse_shared_keys() -> None:
    """The install-wide keys come back only when no two tenants hold the same slug, graph version or digest."""
    bind = op.get_bind()
    agents = table("registry_agents", "slug")
    versions = sa.table("graph_versions", sa.column("name", sa.String), sa.column("version"), sa.column("digest"))
    counts = {
        "agent slugs": sa.select(agents.c.slug).group_by(agents.c.slug).having(sa.func.count() > 1),
        "graph versions": sa.select(versions.c.name, versions.c.version)
        .group_by(versions.c.name, versions.c.version)
        .having(sa.func.count() > 1),
        "graph digests": sa.select(versions.c.digest).group_by(versions.c.digest).having(sa.func.count() > 1),
    }
    held = {
        what: bind.execute(sa.select(sa.func.count()).select_from(q.subquery())).scalar_one()
        for what, q in counts.items()
    }
    if found := {what: n for what, n in held.items() if n}:
        raise RuntimeError(
            "0106 down: held by more than one tenant, so the install-wide keys would fail: "
            + ", ".join(f"{n} {what}" for what, n in found.items())
            + "; remove or rename them before downgrading"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if not op.get_context().as_sql:
        _refuse_shared_keys()
    op.create_table(
        "channel_files",
        sa.Column("file_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
    )
    if dialect == "postgresql":
        for name in TENANTED:
            op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {name} FROM {TENANT_ROLE}")
    op.drop_index(REQUESTS_TEAM, REQUESTS)
    for name, index in INDEXES.items():
        op.drop_index(index, name)
    op.drop_constraint(VERSION_DIGEST, "graph_versions", type_="unique")
    op.drop_constraint(VERSIONS_PK, "graph_versions", type_="primary")
    op.create_primary_key(VERSIONS_PK, "graph_versions", ["name", "version"])
    op.create_unique_constraint("graph_versions_digest_key", "graph_versions", ["digest"])
    op.drop_constraint(AGENT_SLUG, "registry_agents", type_="unique")
    op.create_unique_constraint("registry_agents_slug_key", "registry_agents", ["slug"])
    op.drop_column(REQUESTS, "team_id", mssql_drop_default=True)
    for name in TENANTED:
        op.drop_column(name, "tenant_id", mssql_drop_default=True)
