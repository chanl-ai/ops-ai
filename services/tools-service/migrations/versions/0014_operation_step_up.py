"""a write approval setting that asks the approver for a step-up whatever the approver count (c-057 T012)
Revision ID: tools_0014_step_up
Revises: tools_0013_output_shape
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0014_step_up"
down_revision = "tools_0013_output_shape"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_operations", sa.Column("step_up", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    # Kept so the chain's revert-and-reapply test (tests/test_registry_store.py) still runs end to end.
    op.drop_column("module_operations", "step_up")
