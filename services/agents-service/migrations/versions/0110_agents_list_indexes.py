"""The agents list reads one team's agents in order by update time or version

Revision ID: 0110_agents_list_indexes
Revises: 0109_registry_policies

The agents list pages, sorts and filters in SQL by team, update time and version; without an index that leads with
each after the tenant and team, every page sorts all of the tenant's agents.
"""

from __future__ import annotations

from alembic import op

revision = "0110_agents_list_indexes"
down_revision = "0109_registry_policies"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_registry_agents_team_updated": ["tenant_id", "team_id", "updated_at"],
    "ix_registry_agents_team_version": ["tenant_id", "team_id", "version"],
}


def upgrade() -> None:
    for name, columns in INDEXES.items():
        op.create_index(name, "registry_agents", columns)


def downgrade() -> None:
    for name in INDEXES:
        op.drop_index(name, table_name="registry_agents")
