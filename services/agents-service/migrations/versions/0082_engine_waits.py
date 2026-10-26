"""engine_waits: a workflow step parked on work another service finishes (c-525)

Revision ID: 0082_engine_waits
Revises: 0081_background_jobs_at_text

A step that started long work (a long file read, a call to an outside system) held a worker until it gave up. It now
parks, and a service event or a signed callback finds it by this table: one row per parked step, written with the
run's waiting state and deleted by every resume. Team isolation like engine_runs. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl

revision = "0082_engine_waits"
down_revision = "0081_background_jobs_at_text"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"


def _marked() -> sa.Table:
    return sa.Table(
        "engine_waits",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    op.create_table(
        "engine_waits",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("node_id", sa.String(120), nullable=False),
        sa.Column("iteration", sa.Integer, nullable=False),
        sa.Column("interrupt_id", sa.String(64), nullable=False),
        sa.Column("event", sa.String(120), nullable=False, server_default=""),
        sa.Column("wait_key", sa.String(240), nullable=False, server_default=""),
        sa.Column("due_at", sa.Float()),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "run_id", "node_id", "iteration", name="pk_engine_waits"),
    )
    op.create_index("ix_engine_waits_event", "engine_waits", ["tenant_id", "team_id", "event", "wait_key"])
    dialect = op.get_bind().dialect.name
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [_marked()], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, DELETE ON engine_waits TO {TENANT_ROLE}")
    for statement in isolation_ddl(_marked(), dialect, kind="team", chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    op.drop_index("ix_engine_waits_event", table_name="engine_waits")
    op.drop_table("engine_waits")
