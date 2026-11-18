"""members and api keys indexed by what their lists filter on

The members list filters a team's people by role and by status, and the keys list keeps the keys made for one
target, in SQL (`ops_store.listing.list_page`); with no index leading with those columns after the team, each
filtered page and each facet count scanned the team's rows. Adds the four indexes; the downgrade drops them.

Revision ID: 0041_list_filters
Revises: 0040_role_assignments_by_role
"""

from __future__ import annotations

from alembic import op

revision = "0041_list_filters"
down_revision = "0040_role_assignments_by_role"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_members_team_role", "members", ["team_id", "role"]),
    ("ix_members_team_status", "members", ["team_id", "status"]),
    ("ix_api_keys_team_target_kind", "api_keys", ["team_id", "target_kind"]),
    ("ix_api_keys_team_target_id", "api_keys", ["team_id", "target_id"]),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
