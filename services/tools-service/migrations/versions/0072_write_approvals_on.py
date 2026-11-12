"""write_approvals_on: requires_approval becomes nullable, so a write can have no setting

requires_approval is nullable so a write can store no setting. The gateway does not read it: a tool's own answer is
approval_mode (0073), and a stored true is carried into it by 0074. Stored values are kept as they are. Downgrade
leaves the column nullable: restoring NOT NULL would fail on rows that hold NULL.

Revision ID: tools_0072_write_approvals_on
Revises: tools_0071_account_key
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0072_write_approvals_on"
down_revision = "tools_0071_account_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("module_operations", "requires_approval", existing_type=sa.Boolean(), nullable=True)


def downgrade() -> None:
    return
