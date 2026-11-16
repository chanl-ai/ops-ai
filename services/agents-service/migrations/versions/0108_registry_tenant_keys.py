"""Workflow, widget, deployment and channel keys include the tenant; threads on another tenant's workflow get a copy

Revision ID: 0108_registry_tenant_keys
Revises: 0107_system_reads_agent_pointers

Workflow and widget ids are chosen (a seed file's id, a slug of the widget's first name) and deployment ids are named
by whoever creates one, so two tenants can name the same one, and the channel ledger and delta cursor are keyed by
deployment. Each key leads with the tenant now (docs/architecture/migration/agents-registry-tenancy.md, "Keys and
lookups"): registry_workflows and registry_widgets (tenant_id, id), their version tables (tenant_id, parent, version)
with a composite foreign key to the parent that cascades a delete and a tenant change, deployments (tenant_id, id),
channel_messages (tenant_id, deployment_id, message_key) and channel_cursors (tenant_id, deployment_id). A version or
validation row written under a parent of another tenant takes its parent's tenant first.

A tenant whose threads or publish requests name a workflow held by another tenant (a seeded workflow lives in
`local`) gets its own copy, for exactly those (tenant, workflow id) pairs: the registry_workflows row, its versions and
its graph_versions rows, with name, version and digest unchanged, so a thread's pinned digest still matches once the
policies hold each tenant to its own rows. The source is the `local` row when there is one. Set-based and safe to run
again: each copy is inserted only where the tenant has none.

Stop agents-service before upgrading: the keys change under its upserts, and a running old release would write
versions and channel rows the step does not see (docs/deploy/database.md).

The down path deletes the workflow copies (a non-`local` row whose id `local` also holds, created at the same time),
then refuses, with a count, while two tenants hold one workflow id, widget id, deployment id, channel message or
cursor, since the install-wide keys would fail partway; offline SQL cannot count. graph_versions copies stay: 0106
already keys that table by tenant. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, backfill_ddl

revision = "0108_registry_tenant_keys"
down_revision = "0107_system_reads_agent_pointers"
branch_labels = None
depends_on = None

CHAIN = "agents"
LOCAL = "local"
REQUESTS = "registry_publish_requests"
# Each parent, its version table and the column naming the parent.
PARENTS = {
    "registry_workflows": ("registry_workflow_versions", "workflow_id"),
    "registry_widgets": ("registry_widget_versions", "widget_id"),
}
# Each table whose primary key gains the tenant, with the key after this revision.
KEYS = {
    "registry_workflows": ("tenant_id", "id"),
    "registry_widgets": ("tenant_id", "id"),
    "registry_workflow_versions": ("tenant_id", "workflow_id", "version"),
    "registry_widget_versions": ("tenant_id", "widget_id", "version"),
    "deployments": ("tenant_id", "id"),
    "channel_messages": ("tenant_id", "deployment_id", "message_key"),
    "channel_cursors": ("tenant_id", "deployment_id"),
}
WORKFLOW_COLUMNS = (
    "id",
    "team_id",
    "name",
    "description",
    "trigger",
    "status",
    "published_version",
    "draft",
    "draft_saved_at",
    "draft_saved_by",
    "created_at",
    "updated_at",
)
WORKFLOW_VERSION_COLUMNS = (
    "workflow_id",
    "version",
    "graph",
    "note",
    "changes",
    "published_at",
    "published_by",
    "review_id",
)
GRAPH_VERSION_COLUMNS = ("name", "version", "digest", "definition", "created_at")


def _t(name: str, *columns: str) -> sa.TableClause:
    return sa.table(name, *(sa.column(c, sa.String) for c in columns))


def _fk(child: str, column: str, *, composite: bool) -> str:
    """PostgreSQL's name for the foreign key, which the SQL Server baseline gives it too (deploy/database/mssql.py)."""
    return f"{child}_tenant_id_{column}_fkey" if composite else f"{child}_{column}_fkey"


def _policed(name: str, *, team: bool) -> sa.Table:
    columns = [sa.Column("tenant_id", sa.String(64)), *([sa.Column("team_id", sa.String(64))] if team else [])]
    return sa.Table(name, sa.MetaData(), *columns, info={**TENANT_SCOPED, **TEAM_OWNED} if team else TENANT_SCOPED)


def _every_tenant(dialect: str) -> tuple[list[str], list[str]]:
    """(before, after) reading every tenant's threads and publish requests, as 0106 does."""
    teams = backfill_ddl([_policed("graph_threads", team=True)], dialect, chain=CHAIN, kind="team")
    if dialect != "mssql":
        return teams
    requests = backfill_ddl([_policed(REQUESTS, team=False)], dialect, chain=CHAIN, kind="tenant")
    return teams[0] + requests[0], teams[1] + requests[1]


def _drop_pk(name: str) -> None:
    """Drops the primary key, found by type on SQL Server since an install may carry a generated name."""
    if op.get_bind().dialect.name == "mssql":
        op.execute(
            f"DECLARE @n sysname = (SELECT k.name FROM sys.key_constraints k "
            f"WHERE k.type = 'PK' AND k.parent_object_id = OBJECT_ID(N'{name}')); "
            f"IF @n IS NOT NULL EXEC (N'ALTER TABLE {name} DROP CONSTRAINT ' + QUOTENAME(@n))"
        )
    else:
        op.execute(f"ALTER TABLE {name} DROP CONSTRAINT IF EXISTS {name}_pkey")


def _drop_fks(child: str, parent: str) -> None:
    """Drops every foreign key from `child` to `parent`, found by the tables it joins on SQL Server."""
    if op.get_bind().dialect.name == "mssql":
        op.execute(
            f"DECLARE @n sysname; "
            f"WHILE 1 = 1 BEGIN "
            f"SET @n = (SELECT TOP 1 f.name FROM sys.foreign_keys f WHERE f.parent_object_id = OBJECT_ID(N'{child}') "
            f"AND f.referenced_object_id = OBJECT_ID(N'{parent}')); "
            f"IF @n IS NULL BREAK; "
            f"EXEC (N'ALTER TABLE {child} DROP CONSTRAINT ' + QUOTENAME(@n)); END"
        )
    else:
        column = PARENTS[parent][1]
        for name in (_fk(child, column, composite=False), _fk(child, column, composite=True)):
            op.execute(f"ALTER TABLE {child} DROP CONSTRAINT IF EXISTS {name}")


def _children_follow_parents() -> None:
    """A version or validation row whose parent is in another tenant takes the parent's tenant. Only a row with no
    parent in its own tenant moves: on a first run parent ids are still unique, so it has one; on a second run every
    child already has its own."""
    children = [*PARENTS.items(), ("registry_workflows", ("registry_validations", "workflow_id"))]
    for parent_name, (child_name, column) in children:
        child, parent = _t(child_name, column, "tenant_id"), _t(parent_name, "id", "tenant_id")
        of = sa.select(parent.c.tenant_id).where(parent.c.id == child.c[column])
        op.execute(
            sa.update(child)
            .where(sa.exists(of), ~sa.exists(of.where(parent.c.tenant_id == child.c.tenant_id)))
            .values(tenant_id=of.scalar_subquery())
        )


def _rank(column: sa.ColumnElement[Any]) -> sa.ColumnElement[Any]:
    """Orders a source tenant so `local`, where the seeds live, comes first."""
    return sa.case((column == LOCAL, ""), else_=column)


def _referenced() -> sa.Subquery:
    """(tenant_id, name): each workflow or graph name a tenant's threads or publish requests point at."""
    threads, requests = _t("graph_threads", "tenant_id", "graph"), _t(REQUESTS, "tenant_id", "kind", "subject_id")
    return sa.union(
        sa.select(threads.c.tenant_id, threads.c.graph.label("name")),
        sa.select(requests.c.tenant_id, requests.c.subject_id.label("name")).where(requests.c.kind == "workflow"),
    ).subquery("referenced")


def _copy_workflows() -> None:
    """The registry_workflows row, its versions and its graph_versions for each (tenant, name) another tenant holds."""
    ref = _referenced()
    rows = _t("registry_workflows", "tenant_id", *WORKFLOW_COLUMNS)
    other = _t("registry_workflows", "tenant_id", "id").alias("other")
    source = sa.select(sa.func.min(_rank(other.c.tenant_id))).where(other.c.id == rows.c.id).scalar_subquery()
    held = sa.exists().where(other.c.tenant_id == ref.c.tenant_id, other.c.id == ref.c.name)
    op.execute(
        sa.insert(rows).from_select(
            ["tenant_id", *WORKFLOW_COLUMNS],
            sa.select(ref.c.tenant_id, *(rows.c[c] for c in WORKFLOW_COLUMNS))
            .join_from(ref, rows, rows.c.id == ref.c.name)
            .where(rows.c.tenant_id != ref.c.tenant_id, _rank(rows.c.tenant_id) == source, ~held),
        )
    )
    # Every workflow row of a tenant that lacks a version its source holds: the copies just made, and any a stopped
    # run left without them.
    copy = _t("registry_workflows", "tenant_id", "id")
    versions = _t("registry_workflow_versions", "tenant_id", *WORKFLOW_VERSION_COLUMNS)
    have = _t("registry_workflow_versions", "tenant_id", "workflow_id", "version").alias("have")
    first = sa.select(sa.func.min(_rank(other.c.tenant_id))).where(other.c.id == copy.c.id).scalar_subquery()
    op.execute(
        sa.insert(versions).from_select(
            ["tenant_id", *WORKFLOW_VERSION_COLUMNS],
            sa.select(copy.c.tenant_id, *(versions.c[c] for c in WORKFLOW_VERSION_COLUMNS))
            .join_from(copy, versions, versions.c.workflow_id == copy.c.id)
            .where(
                versions.c.tenant_id != copy.c.tenant_id,
                _rank(versions.c.tenant_id) == first,
                ~sa.exists().where(
                    have.c.tenant_id == copy.c.tenant_id,
                    have.c.workflow_id == copy.c.id,
                    have.c.version == versions.c.version,
                ),
            ),
        )
    )
    graphs = _t("graph_versions", "tenant_id", *GRAPH_VERSION_COLUMNS)
    peer = _t("graph_versions", "tenant_id", "name").alias("peer")
    origin = (
        sa.select(sa.func.min(_rank(peer.c.tenant_id)))
        .where(peer.c.name == graphs.c.name, peer.c.tenant_id != ref.c.tenant_id)
        .scalar_subquery()
    )
    op.execute(
        sa.insert(graphs).from_select(
            ["tenant_id", *GRAPH_VERSION_COLUMNS],
            sa.select(ref.c.tenant_id, *(graphs.c[c] for c in GRAPH_VERSION_COLUMNS))
            .join_from(ref, graphs, graphs.c.name == ref.c.name)
            .where(
                graphs.c.tenant_id != ref.c.tenant_id,
                _rank(graphs.c.tenant_id) == origin,
                ~sa.exists().where(peer.c.tenant_id == ref.c.tenant_id, peer.c.name == ref.c.name),
            ),
        )
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    for parent, (child, _column) in PARENTS.items():
        _drop_fks(child, parent)
    for name in KEYS:
        _drop_pk(name)
    _children_follow_parents()
    for name, key in KEYS.items():
        op.create_primary_key(f"{name}_pkey", name, list(key))
    for parent, (child, column) in PARENTS.items():
        op.create_foreign_key(
            _fk(child, column, composite=True),
            child,
            parent,
            ["tenant_id", column],
            ["tenant_id", "id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        )
    before, after = _every_tenant(dialect)
    for statement in before:
        op.execute(statement)
    _copy_workflows()
    for statement in after:
        op.execute(statement)


def _refuse_shared_keys() -> None:
    """The install-wide keys come back only when no two tenants hold one of them."""
    bind = op.get_bind()
    keys = {
        "workflow ids": ("registry_workflows", ("id",)),
        "widget ids": ("registry_widgets", ("id",)),
        "deployment ids": ("deployments", ("id",)),
        "channel messages": ("channel_messages", ("deployment_id", "message_key")),
        "channel cursors": ("channel_cursors", ("deployment_id",)),
    }
    held: dict[str, int] = {}
    for what, (name, columns) in keys.items():
        t = _t(name, *columns)
        q = sa.select(*t.c).group_by(*t.c).having(sa.func.count() > 1)
        held[what] = bind.execute(sa.select(sa.func.count()).select_from(q.subquery())).scalar_one()
    if found := {what: n for what, n in held.items() if n}:
        raise RuntimeError(
            "0108 down: held by more than one tenant, so the install-wide keys would fail: "
            + ", ".join(f"{n} {what}" for what, n in found.items())
            + "; remove or rename them before downgrading"
        )


def downgrade() -> None:
    rows = _t("registry_workflows", "tenant_id", "id", "created_at")
    seed = _t("registry_workflows", "tenant_id", "id", "created_at").alias("seed")
    # The copies the upgrade made: their versions go with them (the foreign key cascades).
    op.execute(
        sa.delete(rows).where(
            rows.c.tenant_id != LOCAL,
            sa.exists().where(
                seed.c.tenant_id == LOCAL, seed.c.id == rows.c.id, seed.c.created_at == rows.c.created_at
            ),
        )
    )
    if not op.get_context().as_sql:
        _refuse_shared_keys()
    for child, column in PARENTS.values():
        op.drop_constraint(_fk(child, column, composite=True), child, type_="foreignkey")
    for name, key in KEYS.items():
        op.drop_constraint(f"{name}_pkey", name, type_="primary")
        op.create_primary_key(f"{name}_pkey", name, [c for c in key if c != "tenant_id"])
    for parent, (child, column) in PARENTS.items():
        op.create_foreign_key(_fk(child, column, composite=False), child, parent, [column], ["id"], ondelete="CASCADE")
