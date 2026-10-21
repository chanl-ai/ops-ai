"""tool_modules.team_id nullable: the platform tools module is a workspace-level record (c-433)

The module holding send_reply and open_case was owned by the workspace's Security team, so once calls are scoped to
the calling run's team (c-433) every other team's reply would be refused. A module with no team is read and called by
every team, and a held write on it is decided by the calling run's team. The existing platform module (its id is the
platform's constant, PLATFORM_MODULE in ops_tools.modules.seed) moves to no team.

Revision ID: tools_0032_platform_no_team
Revises: tools_0031_response_schema
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0032_platform_no_team"
down_revision = "tools_0031_response_schema"
branch_labels = None
depends_on = None

PLATFORM_MODULE = "mod_platform_tools"


def upgrade() -> None:
    op.alter_column("tool_modules", "team_id", existing_type=sa.String(64), nullable=True)
    modules = sa.table("tool_modules", sa.column("id", sa.String(64)), sa.column("team_id", sa.String(64)))
    op.execute(modules.update().where(modules.c.id == PLATFORM_MODULE).values(team_id=None))


def downgrade() -> None:
    # The former owner is not kept: a module with no team gets an empty one, which no team holds.
    modules = sa.table("tool_modules", sa.column("team_id", sa.String(64)))
    op.execute(modules.update().where(modules.c.team_id.is_(None)).values(team_id=""))
    op.alter_column("tool_modules", "team_id", existing_type=sa.String(64), nullable=False)
