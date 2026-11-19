"""An index for each column the files list filters or sorts on

The list runs on the shared list contract (ops_store.listing.list_page): it filters on purpose, scan status,
sensitivity, read-as type and read path and sorts on name and upload time, each after the tenant. The read-as index
now leads with the type, so the list's filter uses it; the team stays its last column.

Revision ID: files_0015
Revises: files_0014
"""

from __future__ import annotations

from alembic import op

revision = "files_0015"
down_revision = "files_0014"
branch_labels = None
depends_on = None

LISTED = ("name", "purpose", "scan_status", "sensitivity", "uploaded_at", "read_path")


def upgrade() -> None:
    for column in LISTED:
        op.create_index(f"ix_files_{column}", "files", ["tenant_id", column])
    op.drop_index("ix_files_read_as", table_name="files")
    op.create_index("ix_files_read_as", "files", ["tenant_id", "read_as", "team"])


def downgrade() -> None:
    op.drop_index("ix_files_read_as", table_name="files")
    op.create_index("ix_files_read_as", "files", ["tenant_id", "team", "read_as"])
    for column in reversed(LISTED):
        op.drop_index(f"ix_files_{column}", table_name="files")
