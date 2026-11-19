"""mcp_link_isolation: MCP links are held to their team by the database

mcp_links (tools_0077) was filtered only by the team clause the store wrote, so a query that left the clause out could
read another team's links and the tools they name. It now carries the generated policy (ops_store.schema.isolation_ddl)
for ops_tools_tenant, the role every link store transaction runs as, as the team's secrets do (tools_0055).

Revision ID: tools_0079_mcp_link_isolation
Revises: tools_0078_call_caller_name
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "tools_0079_mcp_link_isolation"
down_revision = "tools_0078_call_caller_name"
branch_labels = None
depends_on = None

CHAIN = "tools"
ROLE = "ops_tools_tenant"
TABLE = "mcp_links"


def _marked() -> sa.Table:
    columns = [sa.Column("tenant_id", sa.String(64)), sa.Column("team_id", sa.String(64))]
    return sa.Table(TABLE, sa.MetaData(), *columns, info={**TENANT_SCOPED, **TEAM_OWNED})


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    table = _marked()
    if dialect == "postgresql":
        # The migrating role may own the table; once FORCE is on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {ROLE}")
    elif dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [table], column_type=_column_type, system_user=None):
            op.execute(statement)
    else:
        return
    for statement in isolation_ddl(table, dialect, chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect not in ("postgresql", "mssql"):
        return
    for statement in isolation_drop_ddl(_marked(), dialect):
        op.execute(statement)
    if dialect == "postgresql":
        op.execute(f"REVOKE ALL ON {TABLE} FROM {ROLE}")
