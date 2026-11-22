"""An index for the time a file's extractions list sorts on

The extractions of one file honour `sortBy` (ops_store.listing.list_page) by status and by when each was asked;
status has its index, and the ask time had none after the tenant and team. The downgrade drops it.

Revision ID: 20261122_2026_list_sort_indexes
Revises: documents_0019
"""

from __future__ import annotations

from alembic import op

revision = "20261122_2026_list_sort_indexes"
down_revision = "documents_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_extractions_asked_at", "extractions", ["tenant_id", "team", "asked_at"])


def downgrade() -> None:
    op.drop_index("ix_extractions_asked_at", table_name="extractions")
