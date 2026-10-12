"""gateway calls and review approvals

Revision ID: 0006_gateway
Revises: 0005_leases
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_gateway"
down_revision = "0005_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_calls",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("access", sa.String(length=32), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=True),
        sa.Column("step", sa.String(length=200), nullable=True),
        sa.Column("sub", sa.String(length=200), nullable=False),
        sa.Column("act", sa.String(length=200), nullable=True),
        sa.Column("decision", sa.String(length=8), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("approvers", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("effect", sa.Boolean(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("view", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gateway_calls_thread_id", "gateway_calls", ["thread_id"])
    # At most one call per approved write carries the side effect. A retry of the same call (a node re-run after a
    # crash, a sweeper recovery) conflicts here and gets the first call's result instead of running the tool again.
    op.create_index(
        "ux_gateway_calls_effect",
        "gateway_calls",
        ["thread_id", "step", "tool", "input_hash"],
        unique=True,
        postgresql_where=sa.text("effect"),
    )
    op.create_table(
        "review_approvals",
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("step", sa.String(length=200), nullable=False),
        sa.Column("approver", sa.String(length=200), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("approved_at", sa.String(length=32), nullable=False),
        # One approval per person per step: the same reviewer clicking twice is still one approver.
        sa.PrimaryKeyConstraint("thread_id", "step", "approver"),
    )


def downgrade() -> None:
    op.drop_table("review_approvals")
    op.drop_index("ux_gateway_calls_effect", table_name="gateway_calls")
    op.drop_index("ix_gateway_calls_thread_id", table_name="gateway_calls")
    op.drop_table("gateway_calls")
