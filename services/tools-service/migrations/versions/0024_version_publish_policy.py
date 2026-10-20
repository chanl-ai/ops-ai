"""a version records whether its publish waited for review and the mode it followed (c-139)

A tool module publish follows the team's publish-review mode (always, major, never), read live from platform-service;
each version records whether it waited and which mode it followed, null on versions published before.

Revision ID: tools_0024_version_policy
Revises: tools_0023_drop_self_approval
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0024_version_policy"
down_revision = "tools_0023_drop_self_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_versions", sa.Column("review_required", sa.Boolean, nullable=True))
    op.add_column("module_versions", sa.Column("policy", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("module_versions", "policy")
    op.drop_column("module_versions", "review_required")
