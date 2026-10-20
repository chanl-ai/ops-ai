"""a tool secret may be limited to teams (c-093)

Revision ID: tools_0018_secret_teams
Revises: tools_0017_effect_scope

A secret was readable by every team's tool modules. `teams` lists the teams whose modules may read it; null is every
team, as before, so existing secrets keep resolving for everyone.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0018_secret_teams"
down_revision = "tools_0017_effect_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_secrets", sa.Column("teams", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("tool_secrets", "teams")
