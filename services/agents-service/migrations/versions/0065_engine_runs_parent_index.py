"""engine_runs: an index on (tenant_id, created_by), for the runs a run started (c-310)

A parent run settles when the last run it started ends (RunStore.settle_parents), and every child's status change
looks up its unfinished siblings by `created_by = 'run:<parent>'`. Without an index that read scans the tenant's runs on
every step of every child run.

Revision ID: 0065_engine_runs_parent_index
Revises: 0064_task_assists
"""

from __future__ import annotations

from alembic import op

revision = "0065_engine_runs_parent_index"
down_revision = "0064_task_assists"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_engine_runs_created_by", "engine_runs", ["tenant_id", "created_by"])


def downgrade() -> None:
    op.drop_index("ix_engine_runs_created_by", table_name="engine_runs")
