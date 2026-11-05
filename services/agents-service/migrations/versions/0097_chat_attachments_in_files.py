"""chat_attachments goes: a chat message's files are files-service's

Revision ID: 0097_chat_attachments_in_files
Revises: 0096_system_reads_team_defaults

A file attached in chat is uploaded to files-service as a chat attachment and read through documents-service on each
turn, so agents-service keeps no copy of its metadata or text. The rows here described files in agents-service's own
interim store (`fl_` ids, bytes on the agents host's disk); they are dropped, not moved: the bytes were never in a
store files-service can reach, and messages keep the name of each file, which a later turn reports as no longer in
Files. The downgrade makes the table again, empty, with its grant and team policy. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "0097_chat_attachments_in_files"
down_revision = "0096_system_reads_team_defaults"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
TABLE = "chat_attachments"


def _marked() -> sa.Table:
    return sa.Table(
        TABLE,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        # SQL Server refuses to drop a table its schema-bound security policy names, so the policy goes first.
        for statement in isolation_drop_ddl(_marked(), dialect):
            op.execute(statement)
    op.drop_index("ix_chat_attachments_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="local"),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("owner_email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("mime", sa.String(127), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("pages", sa.JSON, nullable=False),
        sa.Column("truncated", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_chat_attachments_tenant_id", TABLE, ["tenant_id"])
    marked = _marked()
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [marked], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO {TENANT_ROLE}")
    for statement in isolation_ddl(marked, dialect, kind="team", chain=CHAIN):
        op.execute(statement)
