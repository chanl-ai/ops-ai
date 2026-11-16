"""police_tables: the call log, the allow-list, a module's children, mocks, rate windows, plugin bindings, team
defaults and the sending policy are held to their tenant (and team) by the database

These tables were filtered only by the clauses the store wrote, so a statement that left one out read every tenant's
rows. Each now carries the generated policy (ops_store.schema.isolation_ddl) for ops_tools_tenant, the role every store
transaction runs as: by tenant where a row is read across the tenant's teams (the call log, which logs a call on a
module every team shares in the calling team; a module's children, read through their module; the allow-list and its
history; mocks; rate windows), by tenant and team where a row is one team's (plugin bindings, team defaults, the
sending policy and its judgements). gateway_fences holds no tenant and is marked system. tool_modules is not policed
here: a module with no team is read and called by every team, which the generated team policy does not allow.

No backfill: every row already carries its tenant and team, but for the call log's rows written before tools_0015,
which name no tenant. A module id does not say whose call it was (seeded ids repeat across tenants), so those rows stay
unread, as they are today, since every read names a tenant. Indexes: the hosts a module uses by host (a removal looks
them up), a connection's links by connection, and the secret audit by time for its retention sweep. Each is created
only when missing, on both databases: upgrade.sql runs every step in a transaction, where CREATE INDEX CONCURRENTLY
cannot run, so on a large secret_audit (it was written on every poll) build ix_secret_audit_at by hand first,
CONCURRENTLY, as docs/deploy/database.md says, and this step finds it. Plain SQL, so it renders offline; each step
is safe to re-run. Downgrade removes the policies, grants and indexes.

Revision ID: tools_0080_police_tables
Revises: tools_0079_mcp_link_isolation
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "tools_0080_police_tables"
down_revision = "tools_0079_mcp_link_isolation"
branch_labels = None
depends_on = None

CHAIN = "tools"
ROLE = "ops_tools_tenant"

BY_TENANT = (
    "egress_audit",
    "egress_hosts",
    "egress_ranges",
    "gateway_calls",
    "module_approvals",
    "module_egress_hosts",
    "module_operations",
    "module_versions",
    "operation_mocks",
    "operation_rate_windows",
)
BY_TEAM = ("plugin_bindings", "send_checks", "send_policies", "team_defaults")
# A write's claim checks and raises its thread's fence in the same transaction as the call row.
FENCES = "gateway_fences"
SEQUENCES = ("egress_audit_id_seq",)
INDEXES = (
    ("ix_module_egress_hosts_host", "module_egress_hosts", ["tenant_id", "host"]),
    ("ix_connect_links_connection", "connect_links", ["tenant_id", "connection_id"]),
    ("ix_secret_audit_at", "secret_audit", ["at"]),
)


def _marked(name: str) -> sa.Table:
    if name in BY_TEAM:
        columns = [sa.Column("tenant_id", sa.String(64)), sa.Column("team_id", sa.String(64))]
        return sa.Table(name, sa.MetaData(), *columns, info={**TENANT_SCOPED, **TEAM_OWNED})
    return sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    for name, table, columns in INDEXES:
        if dialect == "mssql":
            # SQL Server has no CREATE INDEX IF NOT EXISTS, and SQLAlchemy drops the clause there without a word.
            op.execute(
                f"IF INDEXPROPERTY(OBJECT_ID(N'{table}'), N'{name}', 'IndexID') IS NULL "
                f"CREATE INDEX {name} ON {table} ({', '.join(columns)})"
            )
        else:
            op.create_index(name, table, columns, if_not_exists=True)
    if dialect not in ("postgresql", "mssql"):
        return
    tables = [_marked(n) for n in (*BY_TENANT, *BY_TEAM)]
    if dialect == "postgresql":
        # The migrating role may own the tables; once FORCE is on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
    if dialect == "postgresql":
        for name in (*BY_TENANT, *BY_TEAM, FENCES):
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {ROLE}")
        for sequence in SEQUENCES:
            op.execute(f"GRANT USAGE ON SEQUENCE {sequence} TO {ROLE}")
    else:
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=None):
            op.execute(statement)
    for table in tables:
        for statement in isolation_ddl(table, dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect in ("postgresql", "mssql"):
        for name in (*BY_TENANT, *BY_TEAM):
            for statement in isolation_drop_ddl(_marked(name), dialect):
                op.execute(statement)
    if dialect == "postgresql":
        for sequence in SEQUENCES:
            op.execute(f"REVOKE ALL ON SEQUENCE {sequence} FROM {ROLE}")
        for name in (*BY_TENANT, *BY_TEAM, FENCES):
            op.execute(f"REVOKE ALL ON {name} FROM {ROLE}")
        # Held before this revision: the sign-in store reads a module's operations (tools_0044).
        op.execute(f"GRANT SELECT ON module_operations TO {ROLE}")
    for name, table, _columns in INDEXES:
        op.drop_index(name, table_name=table, if_exists=True)
