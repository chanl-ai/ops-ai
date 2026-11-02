"""connection_isolation: an app's accounts and their history are held to their team by the database (c-616 C2)

connections and connection_audit were filtered only by the team clauses the store wrote; the sign-in rows under them
were already held (tools_0044). connection_audit now carries its connection's team, written with each row, and both
tables carry the generated team policy for ops_tools_tenant, the role every connection-store transaction runs as.
History whose connection is gone has no team to take and is deleted (existing rows are test data, owner 2026-10-26).

Revision ID: tools_0057_connection_isolation
Revises: tools_0056_module_connections
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "tools_0057_connection_isolation"
down_revision = "tools_0056_module_connections"
branch_labels = None
depends_on = None

CHAIN = "tools"
TABLES = ("connections", "connection_audit")


def _marked(name: str) -> sa.Table:
    return sa.Table(
        name,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        # The migrating role may own the tables; once FORCE is on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
    op.execute(
        "DELETE FROM connection_audit WHERE NOT EXISTS (SELECT 1 FROM connections c "
        "WHERE c.tenant_id = connection_audit.tenant_id AND c.id = connection_audit.connection_id)"
    )
    op.add_column("connection_audit", sa.Column("team_id", sa.String(64)))
    op.execute(
        "UPDATE connection_audit SET team_id = (SELECT c.team_id FROM connections c "
        "WHERE c.tenant_id = connection_audit.tenant_id AND c.id = connection_audit.connection_id)"
    )
    op.alter_column("connection_audit", "team_id", existing_type=sa.String(64), nullable=False)
    tables = [_marked(n) for n in TABLES]
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=None):
            op.execute(statement)
    elif dialect != "postgresql":
        return
    # ops_tools_tenant already holds its grants on both (tools_0044).
    for t in tables:
        for statement in isolation_ddl(t, dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect in ("postgresql", "mssql"):
        for name in TABLES:
            for statement in isolation_drop_ddl(_marked(name), dialect):
                op.execute(statement)
    op.drop_column("connection_audit", "team_id")
