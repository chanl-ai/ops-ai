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
`local`) gets its own copy, for exactly those (tenant, workflow id) pairs: the registry_workflows row (without its
draft), its versions and its graph_versions rows, with name, version and digest unchanged, so a thread's pinned digest
still matches once the policies hold each tenant to its own rows. Each copy's source tenant is chosen before any copy
is inserted: `local` when it holds the workflow, else the first holder by name. Each copied workflow version carries
review_id COPIED. Set-based; a second run copies nothing, since each copy is made only where the tenant has none.

Stop agents-service before upgrading: the keys change under its upserts, and a running old release would write
versions and channel rows the step does not see (docs/deploy/database.md).

The down path deletes the workflow copies (a row another tenant also holds whose every version carries COPIED; one
a tenant has published to since is kept), then each graph_versions row another tenant holds with the same name,
version and digest, keeping the workflow's holder, so the copies leave no duplicate that 0106's down would refuse. It
then refuses, with a count, while two tenants hold one workflow id, widget id, deployment id, channel message or
cursor, since the install-wide keys would fail partway; offline SQL cannot count. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, backfill_ddl, mssql_drop_key_ddl, session_table_ddl

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
# A copy starts with no draft.
DRAFT_COLUMNS = ("draft", "draft_saved_at", "draft_saved_by")
# The review_id of every workflow version this step copies: the down path removes a copy only while each of its
# versions still carries it, so a copy a tenant has published to since is kept (and the down path refuses).
COPIED = "copied"
AGENT_PREFIX = "ag_"
# How a thread or deployment names an agent's own graph.
GRAPH = "agent:"
AGENT_COLUMNS = (
    "id",
    "slug",
    "team_id",
    "version",
    "published_version",
    "paused",
    "created_at",
    "updated_at",
    "template_id",
    "protection",
)
AGENT_VERSION_COLUMNS = (
    "agent_id",
    "version",
    "spec",
    "digest",
    "note",
    "changes",
    "saved_at",
    "saved_by",
    "published_at",
    "published_by",
    "review_id",
)
# Each table naming an agent by id, its column, and whether a `kind` column says the row names an agent; each has a
# team and a tenant. Threads and deployments name one by its graph, `agent:<id>`.
AGENT_REFS = (
    ("team_default_agents", "agent_id", False),
    ("widget_deployments", "agent_id", False),
    ("template_copies", "record_id", True),
    (REQUESTS, "subject_id", True),
)
# A person's memories and their audit name the agent they came from; they move with the tenant's references.
MEMORY_TABLES = ("agent_memories", "memory_audit")
# Rows per committed batch; under 5000, where SQL Server escalates row locks to a table lock.
BATCH = 4000


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
    requests = backfill_ddl([_policed(REQUESTS, team=False)], dialect, chain=CHAIN, kind="tenant")
    return teams[0] + requests[0], teams[1] + requests[1]


def _drop_pk(name: str) -> None:
    """Drops the primary key, found by type on SQL Server since an install may carry a generated name."""
    if op.get_bind().dialect.name == "mssql":
        op.execute(mssql_drop_key_ddl(name, "PK"))
    else:
        op.execute(f"ALTER TABLE {name} DROP CONSTRAINT IF EXISTS {name}_pkey")


def _drop_fks(child: str, parent: str) -> None:
    """Drops every foreign key from `child` to `parent`, found by the tables it joins on SQL Server."""
    if op.get_bind().dialect.name == "mssql":
        op.execute(
            f"DECLARE @n sysname, @s nvarchar(max); "
            f"WHILE 1 = 1 BEGIN "
            f"SET @n = (SELECT TOP 1 f.name FROM sys.foreign_keys f WHERE f.parent_object_id = OBJECT_ID(N'{child}') "
            f"AND f.referenced_object_id = OBJECT_ID(N'{parent}')); "
            f"IF @n IS NULL BREAK; "
            f"SET @s = N'ALTER TABLE {child} DROP CONSTRAINT ' + QUOTENAME(@n); EXEC (@s); END"
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


def _session(dialect: str, what: str) -> sa.TableClause:
    """A session table of (tenant_id, name, source): each copy to make and the tenant it is made from."""
    name = f"#{what}_0108" if dialect == "mssql" else f"{what}_0108"
    op.execute(session_table_ddl(name, dialect, [("k", 330), ("tenant_id", 64), ("name", 255), ("source", 64)]))
    return _t(name, "k", "tenant_id", "name", "source")


def _plan(plan: sa.TableClause, held_by: str, column: str) -> None:
    """Lists, before any copy is made, each (tenant, name) a tenant points at but does not hold in `held_by`, with the
    holder it is copied from: `local` when it holds one, else the first tenant by name."""
    ref = _referenced()
    rows = _t(held_by, "tenant_id", column).alias("holder")
    mine = _t(held_by, "tenant_id", column).alias("mine")
    first = sa.func.min(_rank(rows.c.tenant_id))
    op.execute(
        sa.insert(plan).from_select(
            ["k", "tenant_id", "name", "source"],
            sa.select(
                ref.c.tenant_id + sa.literal("/") + ref.c.name,
                ref.c.tenant_id,
                ref.c.name,
                sa.case((first == "", LOCAL), else_=first),
            )
            .join_from(ref, rows, rows.c[column] == ref.c.name)
            .where(
                rows.c.tenant_id != ref.c.tenant_id,
                ~sa.exists().where(mine.c.tenant_id == ref.c.tenant_id, mine.c[column] == ref.c.name),
            )
            .group_by(ref.c.tenant_id, ref.c.name),
        )
    )


def _copy_workflows(dialect: str) -> None:
    """The registry_workflows row, its versions and its graph_versions for each (tenant, name) another tenant holds,
    each from the one source tenant listed before anything is inserted. A copy carries no draft (a person's unsaved
    work stays in its own tenant), and each version it copies is marked COPIED, which the down path finds it by."""
    workflows, graphs = _session(dialect, "workflow_copies"), _session(dialect, "graph_copies")
    _plan(workflows, "registry_workflows", "id")
    _plan(graphs, "graph_versions", "name")
    rows = _t("registry_workflows", "tenant_id", *WORKFLOW_COLUMNS)
    kept = [c for c in WORKFLOW_COLUMNS if c not in DRAFT_COLUMNS]
    op.execute(
        sa.insert(rows).from_select(
            ["tenant_id", *kept],
            sa.select(workflows.c.tenant_id, *(rows.c[c] for c in kept)).join_from(
                workflows, rows, sa.and_(rows.c.id == workflows.c.name, rows.c.tenant_id == workflows.c.source)
            ),
        )
    )
    versions = _t("registry_workflow_versions", "tenant_id", *WORKFLOW_VERSION_COLUMNS)
    copied = [c for c in WORKFLOW_VERSION_COLUMNS if c != "review_id"]
    op.execute(
        sa.insert(versions).from_select(
            ["tenant_id", *copied, "review_id"],
            sa.select(workflows.c.tenant_id, *(versions.c[c] for c in copied), sa.literal(COPIED)).join_from(
                workflows,
                versions,
                sa.and_(versions.c.workflow_id == workflows.c.name, versions.c.tenant_id == workflows.c.source),
            ),
        )
    )
    versions_of = _t("graph_versions", "tenant_id", *GRAPH_VERSION_COLUMNS)
    op.execute(
        sa.insert(versions_of).from_select(
            ["tenant_id", *GRAPH_VERSION_COLUMNS],
            sa.select(graphs.c.tenant_id, *(versions_of.c[c] for c in GRAPH_VERSION_COLUMNS)).join_from(
                graphs,
                versions_of,
                sa.and_(versions_of.c.name == graphs.c.name, versions_of.c.tenant_id == graphs.c.source),
            ),
        )
    )
    for plan in (workflows, graphs):
        op.execute(f"DROP TABLE {plan.name}")


def _agent_id(dialect: str, tenant: sa.ColumnElement[Any], source: sa.ColumnElement[Any]) -> sa.ColumnElement[Any]:
    """A copy's id: `ag_` and the first 24 hex of the MD5 of `<tenant>/<source id>`, the same on both databases, so a
    re-run finds the copy it made and the down path finds each copy from its source."""
    key = sa.cast(tenant + sa.literal("/") + source, sa.String(200))
    if dialect == "mssql":
        # The algorithm and the style are written into the statement: CONVERT takes its style only as a constant.
        digest = sa.func.hashbytes(sa.literal_column("'MD5'"), key)
        hashed = sa.func.convert(sa.literal_column("varchar(32)"), digest, sa.literal_column("2"))
        hexed: sa.ColumnElement[Any] = sa.func.lower(hashed, type_=sa.String)
    else:
        hexed = sa.func.md5(key, type_=sa.String)
    return sa.literal(AGENT_PREFIX) + sa.func.substring(hexed, 1, 24, type_=sa.String)


def _agent_refs() -> sa.Subquery:
    """(tenant_id, team_id, agent_id): each agent a tenant's thread, deployment, team default, widget deployment,
    template copy or publish request points at; an empty team is no team."""
    agents = _t("registry_agents", "id").alias("named")
    threads = _t("graph_threads", "tenant_id", "team_id", "graph")
    deployments = _t("deployments", "tenant_id", "team_id", "graph")
    selects: list[sa.Select[Any]] = [
        sa.select(t.c.tenant_id, t.c.team_id, agents.c.id.label("agent_id")).join_from(
            agents, t, t.c.graph == sa.literal(GRAPH) + agents.c.id
        )
        for t in (threads, deployments)
    ]
    for name, column, kind in AGENT_REFS:
        t = _t(name, "tenant_id", "team_id", column, "kind")
        q = sa.select(t.c.tenant_id, t.c.team_id, t.c[column].label("agent_id"))
        selects.append(q.where(t.c.kind == "agent") if kind else q)
    return sa.union(*selects).subquery("agent_refs")


def _agent_plan(dialect: str) -> sa.TableClause:
    """A session table of (k, tenant_id, frm, dst, team_id): each agent a tenant points at that another tenant holds,
    the id its copy takes, and the copy's team: the one team that points at it, else the holder's team."""
    name = "#agent_copies_0108" if dialect == "mssql" else "agent_copies_0108"
    op.execute(
        session_table_ddl(name, dialect, [("k", 330), ("tenant_id", 64), ("frm", 64), ("dst", 64), ("team_id", 64)])
    )
    plan = _t(name, "k", "tenant_id", "frm", "dst", "team_id")
    refs, holder = _agent_refs(), _t("registry_agents", "tenant_id", "id", "team_id").alias("holder")
    team = sa.func.nullif(refs.c.team_id, "")
    op.execute(
        sa.insert(plan).from_select(
            ["k", "tenant_id", "frm", "dst", "team_id"],
            sa.select(
                refs.c.tenant_id + sa.literal("/") + refs.c.agent_id,
                refs.c.tenant_id,
                refs.c.agent_id,
                _agent_id(dialect, refs.c.tenant_id, refs.c.agent_id),
                sa.case((sa.func.count(sa.distinct(team)) == 1, sa.func.min(team)), else_=holder.c.team_id),
            )
            .join_from(refs, holder, holder.c.id == refs.c.agent_id)
            .where(holder.c.tenant_id != refs.c.tenant_id)
            .group_by(refs.c.tenant_id, refs.c.agent_id, holder.c.team_id),
        )
    )
    return plan


def _repoint(dialect: str, plan: str, before: list[str], after: list[str]) -> str:
    """Points each reference of a plan row's tenant from `frm` to `dst`, BATCH rows at a time, each batch committed
    alone with the policies set aside inside it (as 0105 does). A moved row no longer names `frm`, so every batch
    makes progress and each loop ends."""
    targets = [("graph_threads", "graph", GRAPH, ""), ("deployments", "graph", GRAPH, "")]
    targets += [(n, c, "", " AND {a}.kind = 'agent'" if kind else "") for n, c, kind in AGENT_REFS]
    targets += [(n, "agent_id", "", "") for n in MEMORY_TABLES]
    loops: list[str] = []
    for name, column, prefix, kind in targets:
        x, y = kind.format(a="x"), kind.format(a="y")
        if dialect == "mssql":
            aside = "\n".join(f"    EXEC (N'{s.replace(chr(39), chr(39) * 2)}');" for s in before)
            back = "\n".join(f"    EXEC (N'{s.replace(chr(39), chr(39) * 2)}');" for s in after)
            loops.append(
                f"WHILE 1 = 1\nBEGIN\n    BEGIN TRANSACTION;\n{aside}\n"
                f"    UPDATE TOP ({BATCH}) x SET {column} = '{prefix}' + p.dst FROM {name} x JOIN {plan} p "
                f"ON p.tenant_id = x.tenant_id AND x.{column} = '{prefix}' + p.frm{x};\n    SET @n = @@ROWCOUNT;\n"
                f"{back}\n    COMMIT;\n    IF @n = 0 BREAK;\nEND"
            )
        else:
            # The policies are back before each COMMIT, the last batch's (which finds nothing) included.
            aside = "".join(f"        {s};\n" for s in before)
            back = "".join(f"        {s};\n" for s in after)
            loops.append(
                f"    LOOP\n{aside}"
                f"        UPDATE {name} x SET {column} = '{prefix}' || p.dst FROM {plan} p WHERE p.tenant_id = "
                f"x.tenant_id AND x.{column} = '{prefix}' || p.frm{x} AND x.ctid IN (SELECT y.ctid FROM {name} y "
                f"JOIN {plan} q ON q.tenant_id = y.tenant_id AND y.{column} = '{prefix}' || q.frm{y} LIMIT {BATCH});\n"
                f"        GET DIAGNOSTICS n = ROW_COUNT;\n{back}"
                "        COMMIT;\n        EXIT WHEN n = 0;\n    END LOOP;"
            )
    if dialect == "mssql":
        return "DECLARE @n int;\n" + "\n".join(loops)
    return "DO $$\nDECLARE n integer;\nBEGIN\n" + "\n".join(loops) + "\nEND $$"


def _agent_policies(dialect: str) -> tuple[list[str], list[str]]:
    """(before, after) reading and writing every tenant's rows of the tables that point at an agent."""
    team = [
        _policed(n, team=True)
        for n in ("graph_threads", *(n for n, _c, _k in AGENT_REFS if n != REQUESTS), *MEMORY_TABLES)
    ]
    before, after = backfill_ddl(team, dialect, chain=CHAIN, kind="team")
    requests = backfill_ddl([_policed(REQUESTS, team=False)], dialect, chain=CHAIN, kind="tenant")
    return before + requests[0], after + requests[1]


def _move_references(dialect: str, plan: sa.TableClause) -> None:
    """Runs the batches of `_repoint`, each committing on its own."""
    before, after = _agent_policies(dialect)
    with op.get_context().autocommit_block():
        op.execute(_repoint(dialect, plan.name, before, after))


def _copy_agents(dialect: str) -> None:
    """Each agent a tenant points at that another tenant holds (a seeded agent lives in `local`) becomes that tenant's
    own agent under a new id: the row, with its published version and pause, and every version, each marked COPIED;
    then the tenant's references move to the new id. Agents keep the install-wide key `id` and the runtime serves
    every tenant's agents from one catalogue by id, so a copy cannot take its source's id. Its slug is the source's
    (a seeded workflow names an agent by slug) unless the tenant already holds that slug."""
    before, after = _agent_policies(dialect)
    for statement in before:
        op.execute(statement)
    plan = _agent_plan(dialect)
    rows = _t("registry_agents", "tenant_id", *AGENT_COLUMNS)
    source = _t("registry_agents", "tenant_id", *AGENT_COLUMNS).alias("source")
    taken = _t("registry_agents", "tenant_id", "slug").alias("taken")
    held = _t("registry_agents", "id").alias("held")
    slug = sa.case(
        (
            sa.exists().where(taken.c.tenant_id == plan.c.tenant_id, taken.c.slug == source.c.slug),
            source.c.slug + sa.literal("-") + sa.func.substring(plan.c.dst, 4, 6, type_=sa.String),
        ),
        else_=source.c.slug,
    )
    same = [c for c in AGENT_COLUMNS if c not in ("id", "slug", "team_id")]
    op.execute(
        sa.insert(rows).from_select(
            ["tenant_id", "id", "slug", "team_id", *same],
            sa.select(plan.c.tenant_id, plan.c.dst, slug, plan.c.team_id, *(source.c[c] for c in same))
            .join_from(plan, source, source.c.id == plan.c.frm)
            .where(~sa.exists().where(held.c.id == plan.c.dst)),
        )
    )
    versions = _t("registry_agent_versions", "tenant_id", *AGENT_VERSION_COLUMNS)
    have = _t("registry_agent_versions", "agent_id").alias("have")
    copied = [c for c in AGENT_VERSION_COLUMNS if c not in ("agent_id", "review_id")]
    op.execute(
        sa.insert(versions).from_select(
            ["tenant_id", "agent_id", *copied, "review_id"],
            sa.select(plan.c.tenant_id, plan.c.dst, *(versions.c[c] for c in copied), sa.literal(COPIED))
            .join_from(plan, versions, versions.c.agent_id == plan.c.frm)
            .where(~sa.exists().where(have.c.agent_id == plan.c.dst)),
        )
    )
    for statement in after:
        op.execute(statement)
    _move_references(dialect, plan)
    op.execute(f"DROP TABLE {plan.name}")


def _remove_agent_copies(dialect: str) -> None:
    """Points each tenant's references to an untouched copy (every version still COPIED) back at its source, then
    deletes the copy; its versions go with it by the foreign key. A copy a tenant has saved a version of is kept."""
    before, after = _agent_policies(dialect)
    for statement in before:
        op.execute(statement)
    name = "#agent_copies_0108" if dialect == "mssql" else "agent_copies_0108"
    op.execute(
        session_table_ddl(name, dialect, [("k", 330), ("tenant_id", 64), ("frm", 64), ("dst", 64), ("team_id", 64)])
    )
    plan = _t(name, "k", "tenant_id", "frm", "dst", "team_id")
    copy, source = _t("registry_agents", "tenant_id", "id", "team_id"), _t("registry_agents", "tenant_id", "id")
    source = source.alias("source")
    versions = _t("registry_agent_versions", "agent_id", "review_id")
    op.execute(
        sa.insert(plan).from_select(
            ["k", "tenant_id", "frm", "dst", "team_id"],
            sa.select(copy.c.id, copy.c.tenant_id, copy.c.id, source.c.id, copy.c.team_id)
            .join_from(copy, source, _agent_id(dialect, copy.c.tenant_id, source.c.id) == copy.c.id)
            .where(
                source.c.tenant_id != copy.c.tenant_id,
                sa.exists().where(versions.c.agent_id == copy.c.id, versions.c.review_id == COPIED),
                ~sa.exists().where(
                    versions.c.agent_id == copy.c.id,
                    sa.or_(versions.c.review_id.is_(None), versions.c.review_id != COPIED),
                ),
            ),
        )
    )
    for statement in after:
        op.execute(statement)
    _move_references(dialect, plan)
    rows = _t("registry_agents", "id")
    op.execute(sa.delete(rows).where(sa.exists(sa.select(plan.c.frm).where(plan.c.frm == rows.c.id))))
    op.execute(f"DROP TABLE {plan.name}")


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
    _copy_workflows(dialect)
    for statement in after:
        op.execute(statement)
    _copy_agents(dialect)


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


def _remove_copies() -> None:
    """Deletes the workflow copies the upgrade made (their versions go with them by the foreign key), then each
    graph_versions row another tenant holds with the same name, version and digest, keeping the holder of the workflow,
    else the first tenant by name (`local` first)."""
    rows, others = _t("registry_workflows", "tenant_id", "id"), _t("registry_workflows", "tenant_id", "id").alias("o")
    versions = _t("registry_workflow_versions", "tenant_id", "workflow_id", "review_id")
    of_row = sa.and_(versions.c.tenant_id == rows.c.tenant_id, versions.c.workflow_id == rows.c.id)
    op.execute(
        sa.delete(rows).where(
            sa.exists().where(others.c.id == rows.c.id, others.c.tenant_id != rows.c.tenant_id),
            sa.exists().where(of_row, versions.c.review_id == COPIED),
            ~sa.exists().where(of_row, sa.or_(versions.c.review_id.is_(None), versions.c.review_id != COPIED)),
        )
    )
    graphs = _t("graph_versions", "tenant_id", "name", "version", "digest")
    twin = _t("graph_versions", "tenant_id", "name", "version", "digest").alias("twin")
    workflows = _t("registry_workflows", "tenant_id", "id").alias("w")

    def holds(tenant: sa.ColumnElement[Any]) -> sa.Exists:
        # Two levels below the DELETE, so the deleted table is named for correlation, not added as a FROM.
        return sa.exists().where(workflows.c.tenant_id == tenant, workflows.c.id == graphs.c.name).correlate(graphs)

    def twin_holds() -> sa.Exists:
        held = _t("registry_workflows", "tenant_id", "id").alias("tw")
        return sa.exists().where(held.c.tenant_id == twin.c.tenant_id, held.c.id == twin.c.name)

    op.execute(
        sa.delete(graphs).where(
            sa.exists().where(
                twin.c.name == graphs.c.name,
                twin.c.version == graphs.c.version,
                twin.c.digest == graphs.c.digest,
                twin.c.tenant_id != graphs.c.tenant_id,
                ~holds(graphs.c.tenant_id),
                sa.or_(twin_holds(), _rank(twin.c.tenant_id) < _rank(graphs.c.tenant_id)),
            )
        )
    )


def downgrade() -> None:
    _remove_agent_copies(op.get_bind().dialect.name)
    _remove_copies()
    if not op.get_context().as_sql:
        _refuse_shared_keys()
    for child, column in PARENTS.values():
        op.drop_constraint(_fk(child, column, composite=True), child, type_="foreignkey")
    for name, key in KEYS.items():
        op.drop_constraint(f"{name}_pkey", name, type_="primary")
        op.create_primary_key(f"{name}_pkey", name, [c for c in key if c != "tenant_id"])
    for parent, (child, column) in PARENTS.items():
        op.create_foreign_key(_fk(child, column, composite=False), child, parent, [column], ["id"], ondelete="CASCADE")
