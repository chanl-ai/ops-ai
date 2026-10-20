"""module approvals keep the review that decides them and the team that decides it (c-166)

Revision ID: tools_0025_access_reviews
Revises: tools_0024_version_policy

A workflow's request for a module's operations is decided in Human Tasks: the approval keeps the review's id and the
team whose reviewers decide it. Existing approvals get null; open ones are copied into Reviews once at start.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0025_access_reviews"
down_revision = "tools_0024_version_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_approvals", sa.Column("decider_team", sa.String(64), nullable=True))
    op.add_column("module_approvals", sa.Column("review_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("module_approvals", "review_id")
    op.drop_column("module_approvals", "decider_team")
