"""Saved eval cases and their runs

Revision ID: 0103_eval_cases_runs
Revises: 0102_guardrail_names_per_team

Agents and skills keep the test cases a person saved on them and every run of those cases, so a run can be repeated
and two runs compared; a workflow's runs stay in `registry_validations`. Both tables are team-owned and carry the team
policy like every team-owned table. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "0103_eval_cases_runs"
down_revision = "0102_guardrail_names_per_team"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
TABLES = ("eval_cases", "eval_runs")


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
        "eval_cases",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("review_id", sa.String(64)),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_eval_cases_asset", "eval_cases", ["tenant_id", "team_id", "kind", "asset_id"])
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("live_version", sa.Integer()),
        sa.Column("trigger", sa.String(24), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("live_passed", sa.Integer()),
        sa.Column("regressions", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("started_by", sa.String(320), nullable=False),
        sa.Column("ran_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_eval_runs_asset", "eval_runs", ["tenant_id", "team_id", "kind", "asset_id", "ran_at"])
    if dialect == "mssql":
        for name in TABLES:
            for statement in mssql_predicates_ddl(
                CHAIN, [_marked(name)], column_type=_column_type, system_user=SYSTEM_ROLE
            ):
                op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    for name in TABLES:
        if dialect == "postgresql":
            grant = "SELECT, INSERT, DELETE" if name == "eval_cases" else "SELECT, INSERT"
            op.execute(f"GRANT {grant} ON {name} TO {TENANT_ROLE}")
        for statement in isolation_ddl(_marked(name), dialect, kind="team", chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    for name in reversed(TABLES):
        # SQL Server refuses to drop a table its security policy still names.
        if dialect == "mssql":
            for statement in isolation_drop_ddl(_marked(name), dialect):
                op.execute(statement)
        op.drop_table(name)
