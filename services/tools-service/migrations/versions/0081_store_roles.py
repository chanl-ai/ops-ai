"""store_roles: the grants every store transaction needs, and a system role for the loops that read every tenant

Every tools store now runs its statements as ops_tools_tenant (`Store.tx()`), so that role writes the module registry
it only read before (tools_0044). The start-up catch-up of team defaults, the review hand-over and the sign-in
keep-alive list the teams and records they then work one tenant at a time; that listing runs as ops_tools_system, a
role row-level security does not apply to, whose grants are only the reads those listings make, the relay's marks on
the outbox and the retention sweep's deletes of old secret use rows.

SQL Server: ops_tools_system is a database user without a login that ops_tools_runtime alone may impersonate
(`system_tx`), made and granted by deploy/database/golden/mssql/grants.sql (deploy/database/mssql.py SYSTEM_USERS) as
agents-service's is. The tools predicate functions pass it, as the baseline's do; they are schema-bound to every
policy that uses them, so each policed tools table loses its policy, the four functions are made again with the system
user, and each policy comes back. Downgrade makes them again without it.

Revision ID: tools_0081_store_roles
Revises: tools_0080_police_tables
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import (
    MSSQL_SECURITY,
    TEAM_OWNED,
    TENANT_SCOPED,
    isolation_ddl,
    isolation_drop_ddl,
    member_ddl,
    mssql_predicates_ddl,
    role_ddl,
)

revision = "tools_0081_store_roles"
down_revision = "tools_0080_police_tables"
branch_labels = None
depends_on = None

CHAIN = "tools"
ROLE = "ops_tools_tenant"
SYSTEM_ROLE = "ops_tools_system"
LOGIN = "ops_tools_runtime"
# What the tenant role may now do that it could not: write the registry (it held SELECT on tool_modules, tools_0044).
TENANT_GRANTS = {"tool_modules": "SELECT, INSERT, UPDATE, DELETE"}
# What a listing across tenants reads; nothing else.
SYSTEM_READS = ("team_defaults", "tool_modules", "module_versions", "module_approvals", "module_operations")
# What the system role changes: the relay marks and prunes every tenant's events, the retention sweep deletes secret
# use rows past their age.
SYSTEM_WRITES = {"service_outbox": "SELECT, UPDATE, DELETE", "secret_audit": "SELECT, DELETE"}
# Every tools table a security policy binds to the predicate functions at this revision (tools_0044 to tools_0080):
# a function cannot be dropped while one of them still uses it.
BY_TEAM = (
    "app_credentials",
    "connect_links",
    "connection_audit",
    "connection_tokens",
    "connections",
    "mcp_links",
    "oauth_states",
    "plugin_bindings",
    "secret_audit",
    "send_checks",
    "send_policies",
    "team_defaults",
    "tool_secrets",
)
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


def _marked(name: str) -> sa.Table:
    if name in BY_TEAM:
        columns = [sa.Column("tenant_id", sa.String(64)), sa.Column("team_id", sa.String(64))]
        return sa.Table(name, sa.MetaData(), *columns, info={**TENANT_SCOPED, **TEAM_OWNED})
    return sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _reissue_predicates(system_user: str | None) -> None:
    """SQL Server: every tools policy dropped, the tools predicate functions made again passing `system_user` (or no
    one), and every policy made again."""
    tables = [_marked(n) for n in (*BY_TEAM, *BY_TENANT)]
    for table in tables:
        for statement in isolation_drop_ddl(table, "mssql"):
            op.execute(statement)
    for kind in ("team", "tenant"):
        for part in ("read", "write"):
            fn = f"{MSSQL_SECURITY}.{CHAIN}_{kind}_{part}"
            op.execute(f"IF OBJECT_ID(N'{fn}', N'IF') IS NOT NULL DROP FUNCTION {fn}")
    for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=system_user):
        op.execute(statement)
    for table in tables:
        for statement in isolation_ddl(table, "mssql", chain=CHAIN):
            op.execute(statement)


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "mssql":
        _reissue_predicates(SYSTEM_ROLE)
        return
    if dialect != "postgresql":
        return
    for name, grant in TENANT_GRANTS.items():
        op.execute(f"GRANT {grant} ON {name} TO {ROLE}")
    op.execute(role_ddl(SYSTEM_ROLE, bypass=True))
    for name in SYSTEM_READS:
        op.execute(f"GRANT SELECT ON {name} TO {SYSTEM_ROLE}")
    for name, grant in SYSTEM_WRITES.items():
        op.execute(f"GRANT {grant} ON {name} TO {SYSTEM_ROLE}")
    op.execute(member_ddl(SYSTEM_ROLE, LOGIN))


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "mssql":
        _reissue_predicates(None)
        return
    if dialect != "postgresql":
        return
    for name in (*SYSTEM_READS, *SYSTEM_WRITES):
        op.execute(f"REVOKE ALL ON {name} FROM {SYSTEM_ROLE}")
    for name in TENANT_GRANTS:
        op.execute(f"REVOKE INSERT, UPDATE, DELETE ON {name} FROM {ROLE}")
    # Dropping the role ends the runtime login's membership too. Roles are server-wide: while another database on the
    # server still grants to it, the drop is refused and the role stays, since that database's service needs it.
    op.execute(
        f"DO $$ BEGIN DROP ROLE IF EXISTS {SYSTEM_ROLE}; EXCEPTION WHEN dependent_objects_still_exist THEN NULL; END $$"
    )
