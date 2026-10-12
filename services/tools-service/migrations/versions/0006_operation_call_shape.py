"""an operation's response transform and its own timeout

Revision ID: tools_0006_call_shape
Revises: tools_0005_secrets
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0006_call_shape"
down_revision = "tools_0005_secrets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_operations", sa.Column("response_transform", sa.Text(), nullable=True))
    op.add_column("module_operations", sa.Column("timeout_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("module_operations", "timeout_ms")
    op.drop_column("module_operations", "response_transform")
