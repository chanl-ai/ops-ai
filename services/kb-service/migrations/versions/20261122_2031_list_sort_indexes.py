"""An index for each column the knowledge document and run lists sort on

A source's and a base's documents and a source's runs honour `sortBy` (ops_store.listing.list_page). Each sortable
column had no index leading with it after the tenant and team, so a sorted page read the team's whole table. The
downgrade drops them.

Revision ID: 20261122_2031_list_sort_indexes
Revises: kb_0029
"""

from __future__ import annotations

from alembic import op

revision = "20261122_2031_list_sort_indexes"
down_revision = "kb_0029"
branch_labels = None
depends_on = None

SORTED = {
    "kb_items": ("title", "status", "size", "processed_at"),
    "kb_runs": ("started_at",),
}


def upgrade() -> None:
    for table, columns in SORTED.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, ["tenant_id", "team_id", column])


def downgrade() -> None:
    for table, columns in reversed(SORTED.items()):
        for column in reversed(columns):
            op.drop_index(f"ix_{table}_{column}", table_name=table)
