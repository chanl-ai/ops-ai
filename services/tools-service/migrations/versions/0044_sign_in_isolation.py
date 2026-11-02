"""sign_in_isolation: a person's saved sign-ins are held to their connection's team by the database (c-602)

connection_tokens, oauth_states and connection_environments were filtered only by the tenant the store was given, and
connect_links by the store's team clause: nothing in the database stopped a query that left the clause out. Each now
carries its connection's team and the generated policy (ops_store.schema.isolation_ddl) for ops_tools_tenant, the role
every connection-store transaction runs as; the service's runtime login becomes a member of it (documents_0012 is why).
A sign-in in progress whose connection is gone is deleted rather than given no team: a state lives ten minutes.
connections.available_to, unread since c-509, goes.

Revision ID: tools_0044_sign_in_isolation
Revises: tools_0043_conn_details_health
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import (
    TEAM_OWNED,
    TENANT_SCOPED,
    isolation_ddl,
    isolation_drop_ddl,
    member_ddl,
    mssql_predicates_ddl,
    role_ddl,
)

revision = "tools_0044_sign_in_isolation"
down_revision = "tools_0043_conn_details_health"
branch_labels = None
depends_on = None

CHAIN = "tools"
ROLE = "ops_tools_tenant"
LOGIN = "ops_tools_runtime"
# The tables that take their connection's team in this revision.
CHILDREN = ("connection_tokens", "oauth_states", "connection_environments")
MARKED = (*CHILDREN, "connect_links")
# What a connection-store transaction touches, run as ROLE: the four marked tables, the connection and its audit, and
# the modules its reads join.
GRANTS = {
    **dict.fromkeys(MARKED, "SELECT, INSERT, UPDATE, DELETE"),
    "connections": "SELECT, INSERT, UPDATE, DELETE",
    "connection_audit": "SELECT, INSERT",
    "tool_modules": "SELECT",
    "module_operations": "SELECT",
}


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


def _team_of(table: str) -> str:
    return (
        f"(SELECT c.team_id FROM connections c WHERE c.tenant_id = {table}.tenant_id AND c.id = {table}.connection_id)"
    )


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        # The migrating role may own the tables; once FORCE is on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
    op.execute(
        "DELETE FROM oauth_states WHERE NOT EXISTS (SELECT 1 FROM connections c "
        "WHERE c.tenant_id = oauth_states.tenant_id AND c.id = oauth_states.connection_id)"
    )
    for name in CHILDREN:
        op.add_column(name, sa.Column("team_id", sa.String(64)))
        op.execute(f"UPDATE {name} SET team_id = {_team_of(name)}")
        op.alter_column(name, "team_id", existing_type=sa.String(64), nullable=False)
    op.drop_column("connections", "available_to")
    tables = [_marked(n) for n in MARKED]
    if dialect == "postgresql":
        op.execute(role_ddl(ROLE))
        for name, grant in GRANTS.items():
            op.execute(f"GRANT {grant} ON {name} TO {ROLE}")
        op.execute(f"GRANT USAGE ON SEQUENCE connection_audit_id_seq TO {ROLE}")
        op.execute(member_ddl(ROLE, LOGIN))
    elif dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=None):
            op.execute(statement)
    else:
        return
    for t in tables:
        for statement in isolation_ddl(t, dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect in ("postgresql", "mssql"):
        for name in MARKED:
            for statement in isolation_drop_ddl(_marked(name), dialect):
                op.execute(statement)
    if dialect == "postgresql":
        for name in GRANTS:
            op.execute(f"REVOKE ALL ON {name} FROM {ROLE}")
        op.execute(f"REVOKE ALL ON SEQUENCE connection_audit_id_seq FROM {ROLE}")
    op.add_column("connections", sa.Column("available_to", sa.JSON()))
    for name in reversed(CHILDREN):
        op.drop_column(name, "team_id")
