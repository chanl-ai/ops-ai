"""An index for each column the platform lists sort on

The keys, roles, teams and audit lists honour `sortBy` (ops_store.listing.list_page): keys by name, creation, last
use and expiry after the team; roles by name, teams by status and creation time and the audit list by time, each
after the tenant. With no index leading with those columns, each sorted page read the whole team's or tenant's rows.
The downgrade drops them.

Revision ID: 20261122_2022_list_sort_indexes
Revises: 0046_roles_given_to_groups
"""

from __future__ import annotations

from alembic import op

revision = "20261122_2022_list_sort_indexes"
down_revision = "0046_roles_given_to_groups"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_api_keys_team_name", "api_keys", ["team_id", "name"]),
    ("ix_api_keys_team_created_at", "api_keys", ["team_id", "created_at"]),
    ("ix_api_keys_team_last_used_at", "api_keys", ["team_id", "last_used_at"]),
    ("ix_api_keys_team_expires_at", "api_keys", ["team_id", "expires_at"]),
    ("ix_roles_name", "roles", ["tenant_id", "name"]),
    ("ix_teams_status", "teams", ["tenant_id", "status"]),
    ("ix_teams_created_at", "teams", ["tenant_id", "created_at"]),
    ("ix_audit_entries_at", "audit_entries", ["tenant_id", "at"]),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
