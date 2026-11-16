"""Index a source's links to bases and an item's pieces

kb_base_sources is keyed by base first, so finding a source's bases, and deleting a source, read every link of the
tenant; kb_chunks had no index on its item, so an item's pieces, a re-index and an item's delete read every piece of
the tenant. Each gets an index that leads with the tenant, as every statement names it. Runs on PostgreSQL and SQL
Server.

Revision ID: kb_0027
Revises: kb_0026
"""

from __future__ import annotations

from alembic import op

revision = "kb_0027"
down_revision = "kb_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_kb_base_sources_source", "kb_base_sources", ["tenant_id", "source_id"])
    op.create_index("ix_kb_chunks_item", "kb_chunks", ["tenant_id", "item_id"])


def downgrade() -> None:
    op.drop_index("ix_kb_chunks_item", table_name="kb_chunks")
    op.drop_index("ix_kb_base_sources_source", table_name="kb_base_sources")
