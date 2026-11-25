"""An index for each column the model provider lists sort on

The connections and provider keys lists honour `sortBy` (ops_store.listing.list_page): connections by type, provider
keys by creation and rotation time after the tenant. Each sort had no index leading with its column, so a sorted page
read the whole table. The downgrade drops them.

Revision ID: 20261122_2017_list_sort_indexes
Revises: models_0013
"""

from __future__ import annotations

from alembic import op

revision = "20261122_2017_list_sort_indexes"
down_revision = "models_0013"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_provider_connections_type", "provider_connections", ["type"]),
    ("ix_provider_keys_created_at", "provider_keys", ["tenant_id", "created_at"]),
    ("ix_provider_keys_rotated_at", "provider_keys", ["tenant_id", "rotated_at"]),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
