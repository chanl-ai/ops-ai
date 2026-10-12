"""review decisions recorded before the resume (decide then resume)

Revision ID: 0012_review_decisions
Revises: 0010_mailbox_channel
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_review_decisions"
down_revision = "0010_mailbox_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per paused step: the interrupt id is the decision id, so a repeated decide finds this row and resumes at
    # most once. `resumed_at` stays null until a resume of the thread finished, so a failed resume is retried.
    op.create_table(
        "review_decisions",
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("decision_id", sa.String(64), primary_key=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("decided_by", sa.String(200), nullable=False),
        sa.Column("decided_at", sa.String(32), nullable=False),
        sa.Column("review", sa.JSON, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("run_id", sa.String(80)),
        sa.Column("resumed_at", sa.String(32)),
    )


def downgrade() -> None:
    op.drop_table("review_decisions")
