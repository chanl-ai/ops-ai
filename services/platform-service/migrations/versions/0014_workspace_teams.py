"""each workspace names its security team and its default team for new people (c-202)

Null keeps today's behaviour: the security team is `Settings.security_team_id` and there is no default team.

Revision ID: 0014_workspace_teams
Revises: 0013_team_lifecycle
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_workspace_teams"
down_revision = "0013_team_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("security_team_id", sa.String(64)))
    op.add_column("tenants", sa.Column("default_team_id", sa.String(64)))


def downgrade() -> None:
    op.drop_column("tenants", "default_team_id")
    op.drop_column("tenants", "security_team_id")
