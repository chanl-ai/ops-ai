"""Drop the model-call ledger and the thread budgets: the model gateway keeps both now

Revision ID: 20261126_2300_drop_model_ledger
Revises: 20261126_1200_schedule_teams

Every model call names its budget and replay key to models-service, which reserves, records and replays it
(docs/design/agents-v2/model-gateway.md), so `model_call_records`, `thread_budgets` and their 0104 side tables have no
reader or writer left. Their rows are not copied: installs are reseeded. The down path makes the four tables again,
empty, with their isolation as 0104 and 0120 left it. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.dialect import db_now
from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "20261126_2300_drop_model_ledger"
down_revision = "20261126_1200_schedule_teams"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
LEDGER = ("model_call_records", "thread_budgets")
SIDE = ("model_call_records_unattributed", "thread_budgets_unattributed")
REPLAY_WHERE = sa.text("task IS NOT NULL AND request_hash IS NOT NULL")


def _marked(name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _call_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64)),
        sa.Column("step", sa.String(120), nullable=False),
        sa.Column("task", sa.String(200)),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("model_alias", sa.String(120), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cost_micros", sa.BigInteger(), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("request_hash", sa.String(64)),
        sa.Column("response", sa.JSON()),
        sa.Column("created_at", sa.String(40), nullable=False),
    ]


def _budget_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("max_calls", sa.Integer()),
        sa.Column("max_tokens", sa.BigInteger()),
        sa.Column("max_cost_micros", sa.BigInteger()),
        sa.Column("updated_at", sa.String(40), nullable=False),
    ]


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    # SQL Server refuses to drop a table its security policy still names.
    if dialect == "mssql":
        for name in LEDGER:
            for statement in isolation_drop_ddl(_marked(name), "mssql"):
                op.execute(statement)
    for name in (*SIDE, *LEDGER):
        op.drop_table(name)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    tenant = sa.Column("tenant_id", sa.String(64), nullable=False)
    op.create_table("model_call_records", *_call_columns(), sa.Column("reserved_until", sa.String(40)), tenant.copy())
    op.create_index("ix_model_call_records_thread_id", "model_call_records", ["thread_id"])
    op.create_index(
        "uq_model_call_replay",
        "model_call_records",
        ["thread_id", "task", "request_hash"],
        unique=True,
        postgresql_where=REPLAY_WHERE,
        mssql_where=REPLAY_WHERE,
    )
    op.create_table("thread_budgets", *_budget_columns(), tenant.copy())
    moved = sa.Column("moved_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now())
    op.create_table("model_call_records_unattributed", *_call_columns(), moved.copy())
    op.create_table("thread_budgets_unattributed", *_budget_columns(), moved.copy())
    if dialect == "mssql":
        tables = [_marked(n) for n in LEDGER]
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    for name in LEDGER:
        if dialect == "postgresql":
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {TENANT_ROLE}")
        for statement in isolation_ddl(_marked(name), dialect, chain=CHAIN):
            op.execute(statement)
