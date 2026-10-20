"""a document that indexed with pages unread says which (c-072 review)

Revision ID: kb_0006
Revises: kb_0005

A PDF with some scanned pages indexed the pages that had text and dropped the others without a word; the item now
keeps the parser's warning, so the documents list shows it as it shows a failure's reason.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0006"
down_revision = "kb_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_items", sa.Column("warning", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("kb_items", "warning")
