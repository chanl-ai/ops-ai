"""background_heartbeats and background_jobs: what each background process is doing, and what it did for a team (c-516)

Revision ID: 0078_background_processes
Revises: 0077_channels_and_memories_team

Nothing recorded whether a background loop was running: a worker that stopped looked the same as one with nothing to
do. Each process now writes a heartbeat (one row per process instance, no tenant data, written as the system role) and
logs the jobs it does inside the job's team (team isolation like the chain's other team tables, read by an account
admin's Background page as the system role). Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl

revision = "0078_background_processes"
down_revision = "0077_channels_and_memories_team"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"


def _jobs_marked() -> sa.Table:
    return sa.Table(
        "background_jobs",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    op.create_table(
        "background_heartbeats",
        sa.Column("process", sa.String(64), primary_key=True),
        sa.Column("instance", sa.String(200), primary_key=True),
        sa.Column("started_at", sa.Float(), nullable=False),
        sa.Column("last_run_at", sa.Float()),
        sa.Column("last_ok_at", sa.Float()),
        sa.Column("next_run_at", sa.Float()),
        sa.Column("done_hour", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("waiting", sa.Integer()),
        sa.Column("last_error", sa.String(2000)),
        sa.Column("last_error_at", sa.Float()),
    )
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("process", sa.String(64), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("at", sa.Float(), nullable=False),
    )
    op.create_index("ix_background_jobs_at", "background_jobs", ["tenant_id", "at"])
    dialect = op.get_bind().dialect.name
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(
            CHAIN, [_jobs_marked()], column_type=_column_type, system_user=SYSTEM_ROLE
        ):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "postgresql":
        op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
        bypass = f"CREATE ROLE {SYSTEM_ROLE} NOLOGIN BYPASSRLS"
        op.execute(f"DO $$ BEGIN {bypass}; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON background_heartbeats TO {SYSTEM_ROLE}")
        op.execute(f"GRANT SELECT, INSERT, DELETE ON background_jobs TO {TENANT_ROLE}")
        op.execute(f"GRANT SELECT ON background_jobs TO {SYSTEM_ROLE}")
    for statement in isolation_ddl(_jobs_marked(), dialect, kind="team", chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    op.drop_index("ix_background_jobs_at", table_name="background_jobs")
    op.drop_table("background_jobs")
    op.drop_table("background_heartbeats")
