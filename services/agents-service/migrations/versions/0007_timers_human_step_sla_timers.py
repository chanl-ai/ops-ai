"""human step SLA timers

Revision ID: 0007_timers
Revises: 0006_gateway
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_timers"
down_revision = "0006_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "timers",
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("timer_id", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("node", sa.String(length=64), nullable=False),
        sa.Column("interrupt_id", sa.String(length=64), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("thread_id", "timer_id"),
    )
    # The poller's one query: the earliest open timers. Partial, so fired and cancelled rows cost it nothing.
    op.create_index(
        "ix_timers_due_open",
        "timers",
        ["due_at"],
        postgresql_where=sa.text("fired_at IS NULL AND cancelled_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_timers_due_open", table_name="timers")
    op.drop_table("timers")
