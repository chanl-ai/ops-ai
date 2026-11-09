"""Settings changes reach the account's one audit log

kb_outbox holds each settings change's audit entry, written in the transaction of the change, until its relay delivers
it to platform-service (ops_store.audit). Held to the tenant; ops_kb_system reads, marks and prunes every tenant's for
the relay. Runs on PostgreSQL and SQL Server.

Revision ID: kb_0014
Revises: kb_0013
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "kb_0014"
down_revision = "kb_0013"
branch_labels = None
depends_on = None

CHAIN = "kb"
ROLE = "ops_kb_tenant"
SYSTEM_ROLE = "ops_kb_system"
TABLE = "kb_outbox"


def _marked() -> sa.Table:
    return sa.Table(TABLE, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("event_key", sa.String(length=200), nullable=False),
        sa.Column("actor", sa.String(length=320), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Float(asdecimal=False), nullable=False),
        sa.Column("next_at", sa.Float(asdecimal=False), nullable=True),
        sa.Column("sent_at", sa.Float(asdecimal=False), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kb_outbox_due", TABLE, ["sent_at", "next_at"])
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [_marked()], column_type=_column_type, system_user=None):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {ROLE}")
        op.execute(f"GRANT SELECT, UPDATE, DELETE ON {TABLE} TO {SYSTEM_ROLE}")
    for statement in isolation_ddl(_marked(), dialect, chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(_marked(), dialect):
            op.execute(statement)
    op.drop_index("ix_kb_outbox_due", table_name=TABLE)
    op.drop_table(TABLE)
