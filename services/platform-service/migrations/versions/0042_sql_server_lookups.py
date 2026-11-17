"""SQL Server: the lookups before a tenant is known, as functions that run as platform's system user

On PostgreSQL the tenant role, with no tenant set, reads rows only through the SECURITY DEFINER lookup functions
(0004 to 0035), each returning fixed columns of the rows one exact key names. SQL Server had none of them, and
`system_tx` there impersonated a user that does not exist. This makes `ops_platform_system`, a database user without a
login that nobody is granted IMPERSONATE on, reissues platform's predicate functions so their reads and writes pass
it (each is schema-bound to every policy, so the policies are dropped and made again), and makes one table-valued
function per lookup that runs as it (`ops_platform.store.lookups`). The runtime user's SELECT on the functions is in
grants.sql. It also gives the two keys 0030 and 0034 leave unnamed their PostgreSQL names, which SQL Server had chosen
at random and the golden DDL holds; nothing below names them, so the downgrade leaves the names. Downgrade drops the
functions, reissues the predicates without the user and drops it. Nothing changes on PostgreSQL.

Revision ID: 0042_sql_server_lookups
Revises: 0041_list_filters
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_platform.store.lookups import LOOKUPS, SYSTEM_USER, mssql_function
from ops_store.schema import MSSQL_SECURITY, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "0042_sql_server_lookups"
down_revision = "0041_list_filters"
branch_labels = None
depends_on = None

CHAIN = "platform"
# Every platform table a SQL Server security policy binds to the predicate functions at this revision.
POLICED = (
    "tenants", "teams", "users", "roles", "signin_secrets", "policies", "members", "api_keys", "sessions",
    "audit_entries", "role_permissions", "role_assignments", "signin_providers", "signin_break_glass",
    "password_credentials", "password_resets", "signin_lockouts", "signin_domains", "signin_certificates",
    "signin_group_rules", "signin_identities", "signin_flows", "signin_grants",
)  # fmt: skip


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _policed(name: str) -> sa.Table:
    # `tenants` is isolated by its own key (ops_store.schema.tenant_column), every other table by tenant_id.
    column = (
        sa.Column("id", sa.String(64), primary_key=True) if name == "tenants" else sa.Column("tenant_id", sa.String(64))
    )
    return sa.Table(name, sa.MetaData(), column, info=TENANT_SCOPED)


# (table, referenced table, the key's PostgreSQL name): the keys 0030 and 0034 create without a name.
NAMED_KEYS = (
    ("signin_secrets", "tenants", "signin_secrets_tenant_id_fkey"),
    ("signin_grants", "members", "signin_grants_member_id_fkey"),
)


def _name_key(table: str, referenced: str, name: str) -> str:
    """Gives the table's key to `referenced` the name `name`, unless it already holds it. No SET NOCOUNT ON: it
    outlives the batch on the connection, and alembic's version update then reads a row count of -1 and fails."""
    return (
        f"DECLARE @key_{table} sysname = (SELECT TOP 1 name FROM sys.foreign_keys "
        f"WHERE parent_object_id = OBJECT_ID(N'dbo.{table}') "
        f"AND referenced_object_id = OBJECT_ID(N'dbo.{referenced}'));\n"
        f"IF @key_{table} IS NOT NULL AND @key_{table} <> N'{name}'\n"
        "BEGIN\n"
        f"    DECLARE @old_{table} nvarchar(300) = N'dbo.' + QUOTENAME(@key_{table});\n"
        f"    EXEC sp_rename @old_{table}, N'{name}', N'OBJECT';\n"
        "END"
    )


def _reissue_predicates(system_user: str | None) -> None:
    tables = [_policed(n) for n in POLICED]
    for table in tables:
        for statement in isolation_drop_ddl(table, "mssql"):
            op.execute(statement)
    for part in ("read", "write"):
        fn = f"{MSSQL_SECURITY}.{CHAIN}_tenant_{part}"
        op.execute(f"IF OBJECT_ID(N'{fn}', N'IF') IS NOT NULL DROP FUNCTION {fn}")
    for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=system_user):
        op.execute(statement)
    for table in tables:
        for statement in isolation_ddl(table, "mssql", chain=CHAIN):
            op.execute(statement)


def upgrade() -> None:
    if op.get_context().dialect.name != "mssql":
        return
    for table, referenced, name in NAMED_KEYS:
        op.execute(_name_key(table, referenced, name))
    op.execute(f"IF USER_ID(N'{SYSTEM_USER}') IS NULL CREATE USER {SYSTEM_USER} WITHOUT LOGIN")
    _reissue_predicates(SYSTEM_USER)
    for fn in LOOKUPS:
        op.execute(f"EXEC (N'{mssql_function(fn).replace(chr(39), chr(39) * 2)}')")


def downgrade() -> None:
    if op.get_context().dialect.name != "mssql":
        return
    for fn in LOOKUPS:
        op.execute(f"IF OBJECT_ID(N'dbo.{fn.name}', N'TF') IS NOT NULL DROP FUNCTION dbo.{fn.name}")
    _reissue_predicates(None)
    op.execute(f"IF USER_ID(N'{SYSTEM_USER}') IS NOT NULL DROP USER {SYSTEM_USER}")
