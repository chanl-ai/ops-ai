"""The registry, graph version and channel tables are held to their tenant (and team) by the database

Revision ID: 0109_registry_policies
Revises: 0108_registry_tenant_keys

The stores name the caller's tenant in every lookup and write it on every insert (agents 0108 and the stores beside
it), but nothing in the database held one tenant's rows from another's, and each tenant_id still defaulted to `local`,
so a write that named no tenant landed there (docs/architecture/migration/agents-registry-tenancy.md, "Order",
Migration C). This step:

1. Places the rows still at `local` that belong elsewhere, by the rules of 0106 (ops_agents.store.registry_tenants):
   rows written as `local` between 0106 and the stores that write the caller's tenant. Only a row whose rules give one
   tenant other than `local` moves; one the rules give `local`, or no one tenant (a seeded record several tenants'
   threads use, each of which holds its own copy since 0108), stays where it is, which is where every read already
   looks for it. A move that would take a key the target tenant already holds is skipped and the row stays at `local`:
   a workflow, widget or deployment id (0108 copies), an agent slug, a graph version or digest, a channel message or
   cursor. Widget and workflow versions follow their parent by the composite key's ON UPDATE CASCADE; agent,
   guardrail and skill versions take their parent's tenant explicitly (their parent's id is unique across tenants), as
   do validations and graph versions of a moved workflow, and channel rows of a moved thread or deployment.
2. Drops the `local` server default of every tenant_id 0106 added and of registry_publish_requests (0067), so a write
   that names no tenant is refused.
3. Adds the generated policies (ops_store.schema.isolation_ddl, and on SQL Server the agents predicate functions,
   which pass the agents system user): by tenant and team on registry_agents, registry_guardrails, registry_skills,
   registry_widgets, registry_workflows and deployments; by tenant on registry_publish_requests (whose team a reviewer
   outside the owning team still needs, so it is checked in code), the five version tables, registry_validations,
   graph_versions, channel_messages, channel_cursors and thread_inbox.

The rows to move are listed once, in session tables, inside one transaction that sets the source tables' own policies
aside (on SQL Server each is dropped and made again before that transaction ends); they are then moved BATCH rows at a
time, each batch committed alone, so no lock on a table lasts the whole fill. Stop agents-service before upgrading
(docs/deploy/database.md). Safe to run again: a second run finds nothing left to move.

The down path drops the new policies (registry_publish_requests keeps its tenant policy, which it had before) and
gives each tenant_id its `local` default back. Rows stay in the tenant this step moved them to. Runs on PostgreSQL and
SQL Server.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_agents.store.registry_tenants import (
    DECLARED,
    LOCAL,
    TABLES,
    TEAM_TENANT_SOURCES,
    Declared,
    Placed,
    declared_of,
    table,
    tenant_of,
)
from ops_service_kit.settings import Settings
from ops_store.schema import (
    TEAM_OWNED,
    TENANT_SCOPED,
    backfill_ddl,
    isolation_ddl,
    isolation_drop_ddl,
    mssql_predicates_ddl,
    mssql_quiet_batch,
    session_table_ddl,
)

revision = "0109_registry_policies"
down_revision = "0108_registry_tenant_keys"
branch_labels = None
depends_on = None

CHAIN = "agents"
SYSTEM_ROLE = "ops_runtime_system"
REQUESTS = "registry_publish_requests"
# By tenant and team.
BY_TEAM = (*TABLES.values(),)
VERSIONS = {
    "registry_agent_versions": ("registry_agents", "agent_id"),
    "registry_guardrail_versions": ("registry_guardrails", "guardrail_id"),
    "registry_skill_versions": ("registry_skills", "skill_id"),
}
CASCADED = ("registry_widget_versions", "registry_workflow_versions")
CHANNELS = ("channel_messages", "channel_cursors", "thread_inbox")
# By tenant; registry_publish_requests had its tenant policy before this step.
BY_TENANT = (*VERSIONS, *CASCADED, "registry_validations", "graph_versions", *CHANNELS)
# Every tenant_id that defaulted to `local`.
DEFAULTED = (*BY_TEAM, *BY_TENANT, REQUESTS)
# The kinds whose key leads with the tenant: a move onto a key the target already holds is skipped.
KEYED_BY_TENANT: tuple[Placed, ...] = ("widget", "workflow", "deployment")
# Rows per committed batch; under 5000, where SQL Server escalates row locks to a table lock.
BATCH = 4000


def _marked(name: str) -> sa.Table:
    """The table as far as its policy needs, as of this revision."""
    team = name in BY_TEAM
    columns = [sa.Column("tenant_id", sa.String(64)), *([sa.Column("team_id", sa.String(64))] if team else [])]
    return sa.Table(name, sa.MetaData(), *columns, info={**TENANT_SCOPED, **TEAM_OWNED} if team else TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _every_tenant(dialect: str) -> tuple[list[str], list[str]]:
    """(before, after) reading every tenant's rows of the policed tables the placing rules read, as 0106 does."""
    teams = backfill_ddl([_marked_source(n) for n in TEAM_TENANT_SOURCES], dialect, chain=CHAIN, kind="team")
    requests = backfill_ddl([_marked(REQUESTS)], dialect, chain=CHAIN, kind="tenant")
    return teams[0] + requests[0], teams[1] + requests[1]


def _marked_source(name: str) -> sa.Table:
    columns = [sa.Column("tenant_id", sa.String(64)), sa.Column("team_id", sa.String(64))]
    return sa.Table(name, sa.MetaData(), *columns, info={**TENANT_SCOPED, **TEAM_OWNED})


def _copy(dialect: str, what: str) -> str:
    return f"#{what}_0109" if dialect == "mssql" else f"{what}_0109"


def _list_moves(dialect: str, dev: bool, declared: Declared) -> dict[str, str]:
    """A session table per kind (and for threads) of (k, v): each `local` row's id and the tenant it moves to. Only
    rows that move are listed, so each batch below makes progress and the fill ends."""
    copies = {what: _copy(dialect, what) for what in (*TABLES, "thread")}
    for name in copies.values():
        op.execute(session_table_ddl(name, dialect, [("k", 255), ("v", 64)]))
    for kind, name in TABLES.items():
        row = table(name, "id", "team_id", "tenant_id")
        found = sa.select(row.c.id.label("k"), tenant_of(kind, row, dev=dev, declared=declared).label("v"))
        found = found.where(row.c.tenant_id == LOCAL).subquery("found")
        copy = sa.table(copies[kind], sa.column("k"), sa.column("v"))
        op.execute(
            sa.insert(copy).from_select(
                ["k", "v"], sa.select(found.c.k, found.c.v).where(found.c.v.is_not(None), found.c.v != LOCAL)
            )
        )
    for kind in KEYED_BY_TENANT:
        name, copy = TABLES[kind], copies[kind]
        op.execute(
            f"DELETE FROM {copy} WHERE EXISTS (SELECT 1 FROM {name} t WHERE t.tenant_id = {copy}.v AND t.id = {copy}.k)"
        )
    agents = copies["agent"]
    op.execute(
        f"DELETE FROM {agents} WHERE EXISTS (SELECT 1 FROM registry_agents a JOIN registry_agents b ON b.slug = a.slug "
        f"WHERE a.id = {agents}.k AND b.tenant_id = {agents}.v)"
    )
    # The threads the `local` channel rows name, where the thread is in another tenant.
    op.execute(
        f"INSERT INTO {copies['thread']} (k, v) SELECT g.id, g.tenant_id FROM graph_threads g "
        f"WHERE g.tenant_id <> '{LOCAL}' AND (g.id IN (SELECT i.thread_id FROM thread_inbox i WHERE i.tenant_id = "
        f"'{LOCAL}') OR g.id IN (SELECT m.thread_id FROM channel_messages m WHERE m.tenant_id = '{LOCAL}'))"
    )
    return copies


Extra = Callable[[str, str], str]


def _none(_r: str, _s: str) -> str:
    return ""


def _free(name: str, *columns: str) -> Extra:
    """The target tenant holds no row with this row's `columns`."""

    def extra(r: str, s: str) -> str:
        same = " AND ".join(f"f.{c} = {r}.{c}" for c in columns)
        return f" AND NOT EXISTS (SELECT 1 FROM {name} f WHERE f.tenant_id = {s}.v AND {same})"

    return extra


def _graph_free(r: str, s: str) -> str:
    return (
        f" AND NOT EXISTS (SELECT 1 FROM graph_versions f WHERE f.tenant_id = {s}.v AND "
        f"((f.name = {r}.name AND f.version = {r}.version) OR f.digest = {r}.digest))"
    )


def _fills(copies: dict[str, str]) -> list[tuple[str, str, str, Extra]]:
    """(table, the table's column naming the source key, source of (k, v), extra condition) in the order they run."""
    out: list[tuple[str, str, str, Extra]] = [(name, "id", copies[kind], _none) for kind, name in TABLES.items()]
    for name, (parent, key) in VERSIONS.items():
        # A parent's id is unique across tenants here, so its tenant is the version's, wherever it was placed.
        source = f"(SELECT id AS k, tenant_id AS v FROM {parent} WHERE tenant_id <> '{LOCAL}')"
        out.append((name, key, source, _none))
    out.append(("registry_validations", "workflow_id", copies["workflow"], _none))
    out.append(("graph_versions", "name", copies["workflow"], _graph_free))
    out.append(("thread_inbox", "thread_id", copies["thread"], _none))
    messages = _free("channel_messages", "deployment_id", "message_key")
    out.append(("channel_messages", "thread_id", copies["thread"], messages))
    out.append(("channel_messages", "deployment_id", copies["deployment"], messages))
    out.append(("channel_cursors", "deployment_id", copies["deployment"], _free("channel_cursors", "deployment_id")))
    return out


def _fill(dialect: str, name: str, key: str, source: str, extra: Extra) -> str:
    """Moves `name`'s `local` rows to the source's tenant BATCH rows at a time, each batch committed on its own."""
    if dialect == "mssql":
        return mssql_quiet_batch(
            f"WHILE 1 = 1\nBEGIN\n"
            f"    UPDATE TOP ({BATCH}) r SET tenant_id = s.v FROM {name} r JOIN {source} s ON s.k = r.{key} "
            f"WHERE r.tenant_id = '{LOCAL}'{extra('r', 's')};\n"
            f"    IF @@ROWCOUNT = 0 BREAK;\nEND"
        )
    return (
        f"DO $$\nDECLARE n integer;\nBEGIN\n    LOOP\n"
        f"        UPDATE {name} r SET tenant_id = s.v FROM {source} s WHERE s.k = r.{key} AND r.ctid IN "
        f"(SELECT x.ctid FROM {name} x JOIN {source} y ON y.k = x.{key} WHERE x.tenant_id = '{LOCAL}'"
        f"{extra('x', 'y')} LIMIT {BATCH});\n"
        f"        GET DIAGNOSTICS n = ROW_COUNT;\n        EXIT WHEN n = 0;\n        COMMIT;\n    END LOOP;\nEND $$"
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    offline = op.get_context().as_sql
    # Offline SQL is a DBA script for a real install, never dev: it takes the outside-dev rules.
    dev = not offline and Settings().environment == "dev"
    if dialect in ("postgresql", "mssql"):
        before, after = _every_tenant(dialect)
        for statement in before:
            op.execute(statement)
        # The teams an operator placed by hand for 0106 (docs/deploy/database.md) are placed the same way here.
        copies = _list_moves(dialect, dev, declared_of(os.environ.get(DECLARED, "")))
        for statement in after:
            op.execute(statement)
        with op.get_context().autocommit_block():
            for name, key, source, extra in _fills(copies):
                op.execute(_fill(dialect, name, key, source, extra))
        for copy in copies.values():
            op.execute(f"DROP TABLE {copy}")
    for name in DEFAULTED:
        op.alter_column(name, "tenant_id", existing_type=sa.String(64), existing_nullable=False, server_default=None)
    if dialect not in ("postgresql", "mssql"):
        return
    tables = [_marked(n) for n in (*BY_TEAM, REQUESTS, *BY_TENANT)]
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    for t in tables:
        for statement in isolation_ddl(t, dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for name in (*BY_TEAM, *BY_TENANT):
            for statement in isolation_drop_ddl(_marked(name), dialect):
                op.execute(statement)
    for name in DEFAULTED:
        op.alter_column(name, "tenant_id", existing_type=sa.String(64), existing_nullable=False, server_default=LOCAL)
