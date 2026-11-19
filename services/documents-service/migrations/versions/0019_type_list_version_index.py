"""An index for the document type list's version sort

Revision ID: documents_0019
Revises: documents_0018

The type list sorts on the newest version as well as the name (sortBy=latestVersion), within the team, so its index
leads with the tenant and team. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from alembic import op

revision = "documents_0019"
down_revision = "documents_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_document_types_latest_version", "document_types", ["tenant_id", "team", "latest_version"])


def downgrade() -> None:
    op.drop_index("ix_document_types_latest_version", table_name="document_types")
