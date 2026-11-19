"""tool_approval_mode: an operation's own answer to "who approves a call", beside the team's and its app's

approval_mode is null (follows the app, then the team), none, person or reviewer; reviewer_role narrows which role
decides. Stored rows keep null, so no tool changes its answer. Loosening a tool below its app or team is staged as a
major change, which Security reviews before a call sees it.

Revision ID: tools_0073_tool_approval_mode
Revises: tools_0072_write_approvals_on
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0073_tool_approval_mode"
down_revision = "tools_0072_write_approvals_on"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_operations", sa.Column("approval_mode", sa.String(8), nullable=True))
    op.add_column("module_operations", sa.Column("reviewer_role", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("module_operations", "reviewer_role")
    op.drop_column("module_operations", "approval_mode")
