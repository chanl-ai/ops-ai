"""a source keeps the name its uploader gave each file (c-072)

Revision ID: kb_0005
Revises: kb_0004

The files layer stores one blob per content and keeps the first uploader's name, so a file uploaded again under
another name (a new version of a document, under the document's name) came back named as the earlier upload and
was indexed as a different document. The source now records the name each file was uploaded under.

Nullable with no server default: MySQL 8 refuses a literal default on a JSON column. The store writes `{}` for a new
source and reads a missing map as empty.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0005"
down_revision = "kb_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_sources", sa.Column("file_names", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("kb_sources", "file_names")
