"""An index for each column the tools lists sort on

The call log, the egress allow-list and the secrets list honour `sortBy` (ops_store.listing.list_page). Each sortable
column had no index leading with it after the tenant (and the team, where the table has one), so a sorted page read
the whole table. The downgrade drops them.

Revision ID: 20261122_2038_list_sort_indexes
Revises: tools_0088_app_card_account
"""

from __future__ import annotations

from alembic import op

revision = "20261122_2038_list_sort_indexes"
down_revision = "tools_0088_app_card_account"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_gateway_calls_created_at", "gateway_calls", ["tenant_id", "created_at"]),
    ("ix_gateway_calls_latency_ms", "gateway_calls", ["tenant_id", "latency_ms"]),
    ("ix_egress_hosts_added_at", "egress_hosts", ["tenant_id", "added_at"]),
    ("ix_egress_ranges_added_at", "egress_ranges", ["tenant_id", "added_at"]),
    ("ix_tool_secrets_created_at", "tool_secrets", ["tenant_id", "team_id", "created_at"]),
    ("ix_tool_secrets_rotated_at", "tool_secrets", ["tenant_id", "team_id", "rotated_at"]),
    ("ix_tool_secrets_last_used_at", "tool_secrets", ["tenant_id", "team_id", "last_used_at"]),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
