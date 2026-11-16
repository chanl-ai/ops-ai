"""Index knowledge bases by template

The knowledge-base list filters on `templateId` in SQL (`ops_store.listing.list_page`), which read every base of the
tenant without an index that leads with the column after the tenant. Runs on PostgreSQL and SQL Server.

Revision ID: kb_0028
Revises: kb_0027
"""

from __future__ import annotations

from alembic import op

revision = "kb_0028"
down_revision = "kb_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_kb_bases_template", "kb_bases", ["tenant_id", "template_id"])


def downgrade() -> None:
    op.drop_index("ix_kb_bases_template", table_name="kb_bases")
