"""SQL Server: the kb predicate functions pass kb's system user

kb's loops (the outbox relay, the knowledge schedule, the embedding backlog and the start-up move between file stores)
list every tenant's sources, and the relay marks and prunes every tenant's events, as ops_kb_system (`system_tx`). On
PostgreSQL that role bypasses row security (kb_0011, kb_0014). On SQL Server ops_kb_system is a database user without
a login that ops_kb_runtime alone may impersonate, made and granted by deploy/database/golden/mssql/grants.sql
(deploy/database/mssql.py SYSTEM_USERS); the kb predicate functions made before this revision admitted no system user,
so those listings read nothing. The functions are schema-bound to every policy that uses them, so each policed kb table
loses its policy, the four functions are made again passing the system user, and each policy comes back. Downgrade
makes them again without it. Nothing changes on PostgreSQL.

Revision ID: kb_0026
Revises: kb_0025
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
    mssql_predicates_ddl,
)

revision = "kb_0026"
down_revision = "kb_0025"
branch_labels = None
depends_on = None

CHAIN = "kb"
SYSTEM_ROLE = "ops_kb_system"
# Every kb table a SQL Server security policy binds to the predicate functions at this revision (kb_0011, kb_0014,
# kb_0016); kb_unit_vectors is PostgreSQL only (kb_0021).
BY_TEAM = (
    "kb_bases",
    "kb_sources",
    "kb_base_sources",
    "kb_items",
    "kb_item_versions",
    "kb_chunks",
    "kb_changes",
    "kb_runs",
    "kb_retired_bases",
    "kb_units",
)
BY_TENANT = ("kb_outbox",)


def _marked(name: str) -> sa.Table:
    if name in BY_TEAM:
        columns = [sa.Column("tenant_id", sa.String(64)), sa.Column("team_id", sa.String(64))]
        return sa.Table(name, sa.MetaData(), *columns, info={**TENANT_SCOPED, **TEAM_OWNED})
    return sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _reissue_predicates(system_user: str | None) -> None:
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
    if op.get_context().dialect.name == "mssql":
        _reissue_predicates(SYSTEM_ROLE)


def downgrade() -> None:
    if op.get_context().dialect.name == "mssql":
        _reissue_predicates(None)
