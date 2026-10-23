"""Workflow runs lose their single-column tenant and workflow indexes (c-507)

Revision ID: 0080_drop_runs_single_col_idx
Revises: 0078_background_processes

Every other index on engine_runs leads with tenant_id, so these two added nothing a query needs. Under the team row
policy (0076) the planner took them to read a tenant's runs and sort, instead of reading one team's runs in order from
ix_engine_runs_team_status_created. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from alembic import op

revision = "0080_drop_runs_single_col_idx"
down_revision = "0078_background_processes"
branch_labels = None
depends_on = None

INDEXES = {"ix_engine_runs_tenant_id": "tenant_id", "ix_engine_runs_workflow_id": "workflow_id"}


def upgrade() -> None:
    for name in INDEXES:
        op.drop_index(name, table_name="engine_runs")


def downgrade() -> None:
    for name, column in INDEXES.items():
        op.create_index(name, "engine_runs", [column])
