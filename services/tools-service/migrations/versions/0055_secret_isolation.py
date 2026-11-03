"""secret_isolation: tool secrets, their audit and Ops AI's own app secrets are held by the database

tool_secrets and secret_audit were filtered only by the team clause the store wrote, and plugin_app_keys by its tenant
clause: nothing in the database stopped a query that left the clause out from reading another team's sealed values.
Each now carries the generated policy (ops_store.schema.isolation_ddl) for ops_tools_tenant, the role every secret
store transaction runs as, as the saved sign-ins do (tools_0044): tool_secrets and secret_audit to their team,
plugin_app_keys, the account's and no team's, to its tenant.

Revision ID: tools_0055_secret_isolation
Revises: tools_0054_team_defaults
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "tools_0055_secret_isolation"
down_revision = "tools_0054_team_defaults"
branch_labels = None
depends_on = None

CHAIN = "tools"
ROLE = "ops_tools_tenant"
TEAM_TABLES = ("tool_secrets", "secret_audit")
TENANT_TABLES = ("plugin_app_keys",)
GRANTS = {
    "tool_secrets": "SELECT, INSERT, UPDATE, DELETE",
    "secret_audit": "SELECT, INSERT",
    "plugin_app_keys": "SELECT, INSERT, UPDATE, DELETE",
}
SEQUENCE = "secret_audit_id_seq"


def _marked(name: str) -> sa.Table:
    team = name in TEAM_TABLES
    columns = [sa.Column("tenant_id", sa.String(64)), *([sa.Column("team_id", sa.String(64))] if team else [])]
    return sa.Table(name, sa.MetaData(), *columns, info={**TENANT_SCOPED, **(TEAM_OWNED if team else {})})


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        # The migrating role may own the tables; once FORCE is on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
    tables = [_marked(n) for n in (*TEAM_TABLES, *TENANT_TABLES)]
    if dialect == "postgresql":
        for name, grant in GRANTS.items():
            op.execute(f"GRANT {grant} ON {name} TO {ROLE}")
        op.execute(f"GRANT USAGE ON SEQUENCE {SEQUENCE} TO {ROLE}")
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
    if dialect not in ("postgresql", "mssql"):
        return
    for name in (*TEAM_TABLES, *TENANT_TABLES):
        for statement in isolation_drop_ddl(_marked(name), dialect):
            op.execute(statement)
    if dialect == "postgresql":
        for name in GRANTS:
            op.execute(f"REVOKE ALL ON {name} FROM {ROLE}")
        op.execute(f"REVOKE ALL ON SEQUENCE {SEQUENCE} FROM {ROLE}")
