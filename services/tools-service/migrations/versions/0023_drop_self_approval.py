"""a write's approval no longer carries a per-operation self-approval switch (c-186)

`module_operations.self_approval` was stored and returned but no check read it once the tenant's requesterMayDecide
policy became the one switch (adce035c); a setting that is shown and ignored misleads whoever sets it. Dropped; the
downgrade restores it as false everywhere.

Revision ID: tools_0023_drop_self_approval
Revises: tools_0022_requester_email
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0023_drop_self_approval"
down_revision = "tools_0022_requester_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("module_operations", "self_approval")


def downgrade() -> None:
    op.add_column(
        "module_operations", sa.Column("self_approval", sa.Boolean, nullable=False, server_default=sa.false())
    )
