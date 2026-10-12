"""model call ledger

Revision ID: 0014_model_calls
Revises: 0013_usage_and_budgets
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_model_calls"
down_revision = "0013_usage_and_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One committed model response per thread and request: a graph node re-run after a crash replays it.
    op.create_table(
        "model_calls",
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("thread_id", "request_hash"),
    )


def downgrade() -> None:
    op.drop_table("model_calls")
