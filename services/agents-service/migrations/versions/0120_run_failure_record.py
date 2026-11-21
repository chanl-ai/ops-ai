"""engine_runs.failure: the run's error in the one error model

Revision ID: 0120_run_failure_record
Revises: 0119_unattributed_side_tables

A failed or Stuck run kept only a sentence in `error`, so the run view could not say which kind of failure it was or
whether a retry helps. `failure` holds ops_contracts.errors.RunError beside it. Nullable with no default, so adding it
rewrites no rows on PostgreSQL or SQL Server; a run that failed before reads as `internal_error` (or `stuck`).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0120_run_failure_record"
down_revision = "0119_unattributed_side_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("engine_runs", sa.Column("failure", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("engine_runs", "failure")
