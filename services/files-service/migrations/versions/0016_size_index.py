"""An index for the files list's size sort

The list sorts on size as well as name and upload time (sortBy=size); scan status and purpose already have theirs.

Revision ID: files_0016
Revises: files_0015
"""

from __future__ import annotations

from alembic import op

revision = "files_0016"
down_revision = "files_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_files_size", "files", ["tenant_id", "size"])


def downgrade() -> None:
    op.drop_index("ix_files_size", table_name="files")
