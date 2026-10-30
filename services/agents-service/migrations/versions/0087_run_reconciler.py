"""The run reconciler (c-561): a work row counts the times its claim lapsed, and the system role reads runs and steps

Revision ID: 0087_run_reconciler
Revises: 0086_memory_text_unindexed

A claim lapses when its worker died; `attempts` also counts claims given back because the run's lease was busy, so it
cannot tell a run that kills its worker from one that waited. The reconciler finds runs with nothing behind them
across tenants, so the system role reads engine_runs and engine_steps as it already reads engine_work; it changes a
run only inside the run's tenant. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0087_run_reconciler"
down_revision = "0086_memory_text_unindexed"
branch_labels = None
depends_on = None

SYSTEM_ROLE = "ops_runtime_system"


def upgrade() -> None:
    op.add_column("engine_work", sa.Column("lapses", sa.Integer, nullable=False, server_default="0"))
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT ON engine_runs TO {SYSTEM_ROLE}")
        op.execute(f"GRANT SELECT ON engine_steps TO {SYSTEM_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE SELECT ON engine_steps FROM {SYSTEM_ROLE}")
        op.execute(f"REVOKE SELECT ON engine_runs FROM {SYSTEM_ROLE}")
    op.drop_column("engine_work", "lapses")
