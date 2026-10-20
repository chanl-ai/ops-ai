"""engine_runs: indexes for the runs list and for a parent's unfinished runs (c-312, tick 30)

The runs list reads one team's runs newest first, optionally by status, and counts them per status
(RunStore.page). Without an index each page sorted every run the tenant has. The parent index gains `status`, so
settling a parent looks up its waiting or unfinished runs directly instead of reading every run it started on each
child's status change.

Revision ID: 0066_engine_runs_list_indexes
Revises: 0065_engine_runs_parent_index
"""

from __future__ import annotations

from alembic import op

revision = "0066_engine_runs_list_indexes"
down_revision = "0065_engine_runs_parent_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_engine_runs_team_created", "engine_runs", ["tenant_id", "team_id", "created_at"])
    op.create_index(
        "ix_engine_runs_team_status_created", "engine_runs", ["tenant_id", "team_id", "status", "created_at"]
    )
    op.drop_index("ix_engine_runs_created_by", table_name="engine_runs")
    op.create_index("ix_engine_runs_parent_status", "engine_runs", ["tenant_id", "created_by", "status"])


def downgrade() -> None:
    op.drop_index("ix_engine_runs_parent_status", table_name="engine_runs")
    op.create_index("ix_engine_runs_created_by", "engine_runs", ["tenant_id", "created_by"])
    op.drop_index("ix_engine_runs_team_status_created", table_name="engine_runs")
    op.drop_index("ix_engine_runs_team_created", table_name="engine_runs")
