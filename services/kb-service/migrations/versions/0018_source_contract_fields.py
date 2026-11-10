"""Items keep where they sit at their source, their fields, their version tag, and who may see each version

The knowledge-source contract gives each fetched item a folder path and fields (columns, labels, properties) that the
source's metadata mapping reads, and each version the ids the source system lets see it (`allowed`). They are kept so
a rebuild from the snapshot maps the same metadata, and per-item access can be enforced later from what was stored.
`tag` is the version tag the fetch gave (an ETag, md5 or revision), sent back so the system can answer unchanged.
Runs on PostgreSQL and SQL Server.

Revision ID: kb_0018
Revises: kb_0017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0018"
down_revision = "kb_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_items", sa.Column("folder", sa.String(400), nullable=True))
    op.add_column("kb_items", sa.Column("fields", sa.JSON(), nullable=True))
    op.add_column("kb_items", sa.Column("tag", sa.String(200), nullable=True))
    op.add_column("kb_item_versions", sa.Column("allowed", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kb_item_versions") as b:
        b.drop_column("allowed")
    with op.batch_alter_table("kb_items") as b:
        b.drop_column("tag")
        b.drop_column("fields")
        b.drop_column("folder")
