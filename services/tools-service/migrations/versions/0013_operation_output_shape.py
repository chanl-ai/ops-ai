"""an operation's declared result shape (x-ops-shape), for the chat's widget shaper

Revision ID: tools_0013_output_shape
Revises: tools_0012_access_rw
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0013_output_shape"
down_revision = "tools_0012_access_rw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_operations", sa.Column("output_shape", sa.String(16), nullable=True))


def downgrade() -> None:
    # Kept so the chain's revert-and-reapply test (tests/test_registry_store.py) still runs end to end.
    op.drop_column("module_operations", "output_shape")
