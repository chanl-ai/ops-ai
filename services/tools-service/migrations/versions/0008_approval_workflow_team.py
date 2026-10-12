"""the team owning an approval's workflow, from agents-service

Revision ID: tools_0008_approval_team
Revises: tools_0007_rate_windows
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0008_approval_team"
down_revision = "tools_0007_rate_windows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_approvals", sa.Column("workflow_team_id", sa.String(64), nullable=True))


def downgrade() -> None:
    # Kept so the chain's revert-and-reapply test (tests/test_registry_store.py) still runs end to end.
    op.drop_column("module_approvals", "workflow_team_id")
