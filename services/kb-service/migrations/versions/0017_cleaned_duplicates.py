"""An item knows its cleaned content, and which newer item repeats it

kb_items.content_digest is the digest of the item's text after cleaning, so two items with the same content in a
knowledge base are found whatever their files or addresses. duplicate_of names the newer item that repeats an older
one; search leaves the older one out. Runs on PostgreSQL and SQL Server.

Revision ID: kb_0017
Revises: kb_0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0017"
down_revision = "kb_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_items", sa.Column("content_digest", sa.String(80), nullable=True))
    op.add_column("kb_items", sa.Column("duplicate_of", sa.String(64), nullable=True))
    op.create_index("ix_kb_items_content", "kb_items", ["tenant_id", "content_digest"])


def downgrade() -> None:
    op.drop_index("ix_kb_items_content", table_name="kb_items")
    with op.batch_alter_table("kb_items") as b:
        b.drop_column("duplicate_of")
        b.drop_column("content_digest")
