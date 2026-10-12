"""timer claims fenced by lease generation, and a retry cap

Revision ID: 0009_timer_claims
Revises: 0008_lease_generation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_timer_claims"
down_revision = "0008_lease_generation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A fire claims its timer with the lease generation it holds, instead of locking the row for the step's whole
    # run (ADR-0016). A newer generation may re-claim a timer whose firing never finished.
    op.add_column("timers", sa.Column("claimed_generation", sa.BigInteger(), nullable=True))
    op.add_column("timers", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("timers", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    # Set when the retry cap is reached: the timer leaves the poller's queue and waits for a person.
    op.add_column("timers", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_index("ix_timers_due_open", table_name="timers")
    op.create_index(
        "ix_timers_due_open",
        "timers",
        ["due_at"],
        postgresql_where=sa.text("fired_at IS NULL AND cancelled_at IS NULL AND failed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_timers_due_open", table_name="timers")
    op.create_index(
        "ix_timers_due_open",
        "timers",
        ["due_at"],
        postgresql_where=sa.text("fired_at IS NULL AND cancelled_at IS NULL"),
    )
    for column in ("failed_at", "attempts", "claimed_at", "claimed_generation"):
        op.drop_column("timers", column)
