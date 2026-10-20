"""what was read from a file (c-250)

The extract workflow records on the file the document type and version it was read as, template or model, the fields
waiting for a person and the extraction, so the files list shows and filters "read as" without asking another
service per row. `read_as` and `read_path` repeat the type and path as columns for the filters and their counts.

Revision ID: files_0007
Revises: files_0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "files_0007"
down_revision = "files_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("files", sa.Column("data", sa.JSON))
    op.add_column("files", sa.Column("read_as", sa.String(64)))
    op.add_column("files", sa.Column("read_path", sa.String(16)))
    op.create_index("ix_files_read_as", "files", ["tenant_id", "team", "read_as"])


def downgrade() -> None:
    pass
