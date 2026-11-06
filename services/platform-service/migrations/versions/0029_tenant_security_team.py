"""each workspace's record names its Security team; no install setting stands in for it

Until now a workspace with no `tenants.security_team_id` used the install's `security_team_id` setting, whose value
every deployment left at its default, `team_security`. This writes that value into each such workspace that has the
team, so the record says what applied before; a workspace without it names none, and nobody holds the Security
team's actions there until an admin names one. Portable SQL only.

Revision ID: 0029_tenant_security_team
Revises: 0028_builder_every_team_cell
"""

from __future__ import annotations

from alembic import op

revision = "0029_tenant_security_team"
down_revision = "0028_builder_every_team_cell"
branch_labels = None
depends_on = None

# The install setting's default, which every deployment used.
TEAM = "team_security"


def upgrade() -> None:
    op.execute(
        f"UPDATE tenants SET security_team_id = '{TEAM}' WHERE security_team_id IS NULL AND EXISTS "
        f"(SELECT 1 FROM teams WHERE teams.tenant_id = tenants.id AND teams.id = '{TEAM}')"
    )


def downgrade() -> None:
    # Clears the value upgrade wrote. A workspace an admin set to the same team is cleared too, which the code before
    # this revision reads as that same team, so every workspace keeps the Security team it had.
    op.execute(
        f"UPDATE tenants SET security_team_id = NULL WHERE security_team_id = '{TEAM}' AND EXISTS "
        f"(SELECT 1 FROM teams WHERE teams.tenant_id = tenants.id AND teams.id = '{TEAM}')"
    )
