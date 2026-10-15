"""each operation carries its write approval policy: approvers, approver team, self-approval

Revision ID: tools_0011_approval_policy
Revises: tools_0010_replay_of
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0011_approval_policy"
down_revision = "tools_0010_replay_of"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_operations", sa.Column("approvers", sa.Integer, nullable=False, server_default="1"))
    op.add_column("module_operations", sa.Column("approver_team", sa.String(64), nullable=True))
    op.add_column("module_operations", sa.Column("self_approval", sa.Boolean, nullable=False, server_default="false"))


def downgrade() -> None:
    # Kept so the chain's revert-and-reapply test (tests/test_registry_store.py) still runs end to end.
    op.drop_column("module_operations", "self_approval")
    op.drop_column("module_operations", "approver_team")
    op.drop_column("module_operations", "approvers")
