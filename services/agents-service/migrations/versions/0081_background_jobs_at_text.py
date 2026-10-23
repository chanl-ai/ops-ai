"""background_jobs.at holds an ISO time, like every other row Activity lists (c-516)

Revision ID: 0081_background_jobs_at_text
Revises: 0080_drop_runs_single_col_idx

Activity unions every kind into one list ordered by an ISO `at`; a job's float time could not join it. The table is a
day old and holds only test rows, which are dropped with the column. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0081_background_jobs_at_text"
down_revision = "0080_drop_runs_single_col_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM background_jobs"))
    op.drop_index("ix_background_jobs_at", table_name="background_jobs")
    op.drop_column("background_jobs", "at")
    op.add_column("background_jobs", sa.Column("at", sa.String(32), nullable=False, server_default=""))
    op.create_index("ix_background_jobs_at", "background_jobs", ["tenant_id", "at"])


def downgrade() -> None:
    op.drop_index("ix_background_jobs_at", table_name="background_jobs")
    op.drop_column("background_jobs", "at")
    op.add_column("background_jobs", sa.Column("at", sa.Float(), nullable=False, server_default="0"))
    op.create_index("ix_background_jobs_at", "background_jobs", ["tenant_id", "at"])
