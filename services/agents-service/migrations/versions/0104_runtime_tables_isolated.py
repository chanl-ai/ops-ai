"""A thread's budget and its model-call ledger are held to the thread's tenant by the database

Revision ID: 0104_runtime_tables_isolated
Revises: 0103_eval_cases_runs

thread_budgets and model_call_records had no tenant column, so any statement that named a thread id read or wrote that
thread's budget and its recorded model responses whatever tenant asked. Each now carries the tenant of its thread
(backfilled from graph_threads; a row whose thread is gone keeps the dev tenant, "local", as in 0021 and 0067) and the
generated tenant policy. Neither has a team column: a budget and a call are reached only through their thread, whose
own policy holds the team. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import (
    TEAM_OWNED,
    TENANT_SCOPED,
    backfill_ddl,
    isolation_ddl,
    isolation_drop_ddl,
    mssql_predicates_ddl,
)

revision = "0104_runtime_tables_isolated"
down_revision = "0103_eval_cases_runs"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
TABLES = ("thread_budgets", "model_call_records")


def _marked(name: str) -> sa.Table:
    """The table as far as its isolation needs, as of this revision."""
    return sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _threads() -> sa.Table:
    return sa.Table(
        "graph_threads",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    for name in TABLES:
        with op.batch_alter_table(name) as b:
            b.add_column(sa.Column("tenant_id", sa.String(64), nullable=False, server_default="local"))
    # Every tenant's threads are read to fill the column, so graph_threads' own policy is set aside for the backfill.
    before, after = backfill_ddl([_threads()], dialect, chain=CHAIN)
    for statement in before:
        op.execute(statement)
    for name in TABLES:
        op.execute(
            f"UPDATE {name} SET tenant_id = (SELECT g.tenant_id FROM graph_threads g WHERE g.id = {name}.thread_id) "
            f"WHERE EXISTS (SELECT 1 FROM graph_threads g WHERE g.id = {name}.thread_id)"
        )
    for statement in after:
        op.execute(statement)
    if dialect == "mssql":
        tables = [_marked(t) for t in TABLES]
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    for name in TABLES:
        if dialect == "postgresql":
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {TENANT_ROLE}")
        for statement in isolation_ddl(_marked(name), dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for name in TABLES:
            for statement in isolation_drop_ddl(_marked(name), dialect):
                op.execute(statement)
            if dialect == "postgresql":
                op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {name} FROM {TENANT_ROLE}")
    for name in TABLES:
        with op.batch_alter_table(name) as b:
            b.drop_column("tenant_id")
