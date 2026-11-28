"""An item names the PDF its Word file or deck was drawn into

documents-service draws a Word file or deck as a PDF for the document view; the item that shows it holds a Files
reference on that PDF as its source and names it here, so the reference is released when the item lets its file go.
Null for every other item; nothing is backfilled, as the next reading of a drawn file names its PDF. Runs on
PostgreSQL and SQL Server.

Revision ID: 20261127_1200_item_rendition
Revises: 20261122_2031_list_sort_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261127_1200_item_rendition"
down_revision = "20261122_2031_list_sort_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_items", sa.Column("rendition_id", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kb_items") as b:
        b.drop_column("rendition_id")
