"""Batches (c-535)

Revision ID: 0092_run_batches
Revises: 0091_form_links

A workflow can be started once per row of a CSV or Excel file. run_batches holds one row per batch, in the team that
started it, and run_batch_rows one row per file row with its input, its attempt and the run that attempt started; both
carry the team policy like every team-owned table. The workflow worker reads every tenant's pending rows as the system
role and starts each inside its own tenant and team. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl

revision = "0092_run_batches"
down_revision = "0091_form_links"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
TABLES = ("run_batches", "run_batch_rows")


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
    dialect = op.get_bind().dialect.name
    op.create_table(
        "run_batches",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("workflow_id", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("file_id", sa.String(64), nullable=False),
        sa.Column("file_name", sa.String(300), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("stopped_reason", sa.String(500)),
        sa.Column("stopped_at", sa.String(32)),
    )
    op.create_index("ix_run_batches_workflow", "run_batches", ["tenant_id", "workflow_id", "created_at"])
    op.create_table(
        "run_batch_rows",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("batch_id", sa.String(64), nullable=False),
        sa.Column("row", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("run_id", sa.String(64)),
        sa.PrimaryKeyConstraint("tenant_id", "batch_id", "row", name="pk_run_batch_rows"),
    )
    op.create_index("ix_run_batch_rows_pending", "run_batch_rows", ["status", "tenant_id", "batch_id", "row"])
    marked = [_marked(t) for t in TABLES]
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, marked, column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "postgresql":
        for table in TABLES:
            op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {TENANT_ROLE}")
            op.execute(f"GRANT SELECT ON {table} TO {SYSTEM_ROLE}")
    for table in marked:
        for statement in isolation_ddl(table, dialect, kind="team", chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    op.drop_index("ix_run_batch_rows_pending", table_name="run_batch_rows")
    op.drop_table("run_batch_rows")
    op.drop_index("ix_run_batches_workflow", table_name="run_batches")
    op.drop_table("run_batches")
