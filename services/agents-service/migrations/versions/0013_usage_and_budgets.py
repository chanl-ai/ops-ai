"""usage rows per model call, thread budgets, a default budget per deployment (E12)

Revision ID: 0013_usage_and_budgets
Revises: 0012_review_decisions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_usage_and_budgets"
down_revision = "0012_review_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("node", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("model_alias", sa.String(120), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cost_micros", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_usage_records_thread_id", "usage_records", ["thread_id"])
    op.create_table(
        "thread_budgets",
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("max_calls", sa.Integer(), nullable=True),
        sa.Column("max_tokens", sa.BigInteger(), nullable=True),
        sa.Column("max_cost_micros", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.add_column("deployments", sa.Column("budget", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("deployments", "budget")
    op.drop_table("thread_budgets")
    op.drop_index("ix_usage_records_thread_id", table_name="usage_records")
    op.drop_table("usage_records")
