"""write_approvals_on: requires_approval becomes nullable, so a write can have no setting

requires_approval is nullable: NULL follows the team's switches (a write with no setting runs unless the team's
toolWritesNeedApproval or appWritesNeedApproval holds it), true waits, false runs at once. Stored values are kept
as they are. Downgrade leaves the column nullable: restoring NOT NULL would fail on rows that hold NULL.

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
