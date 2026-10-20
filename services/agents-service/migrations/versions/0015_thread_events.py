"""thread event log written as events happen

Revision ID: 0015_thread_events
Revises: 0014_model_calls
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_thread_events"
down_revision = "0014_model_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "thread_events",
        # Global order for the per-team stream's cursor; `seq` is the per-thread order clients see.
        sa.Column(
            "position", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True
        ),
        sa.Column("id", sa.String(40), nullable=False, unique=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("run_id", sa.String(80)),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("node", sa.String(120)),
        sa.Column("at", sa.String(32), nullable=False),
        sa.Column("data", sa.JSON),
        sa.Column("team_id", sa.String(64), nullable=False),
        # Unique: two appends that read the same last seq cannot both land; the loser retries with the next one.
        sa.UniqueConstraint("thread_id", "seq", name="uq_thread_events_thread_seq"),
    )
    op.create_index("ix_thread_events_run", "thread_events", ["thread_id", "run_id", "seq"])
    op.create_index("ix_thread_events_team_position", "thread_events", ["team_id", "position"])


def downgrade() -> None:
    op.drop_table("thread_events")
