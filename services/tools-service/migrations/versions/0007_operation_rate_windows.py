"""per-operation rate counters for the gateway's rate limit

Revision ID: tools_0007_rate_windows
Revises: tools_0006_call_shape
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0007_rate_windows"
down_revision = "tools_0006_call_shape"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_rate_windows",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("operation", sa.String(200), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("calls", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    # Kept so the chain's revert-and-reapply test (tests/test_registry_store.py) still runs end to end.
    op.drop_table("operation_rate_windows")
