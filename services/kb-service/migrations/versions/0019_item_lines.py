"""Items keep a digest of each line of their text, for lines repeated across a site

kb_items.lines holds a short digest of each paragraph of the item's cleaned text. A website source counts them across
its pages, and a line found on more than half of them (a footer the furniture rules missed, a disclaimer bar) is
dropped before splitting. Runs on PostgreSQL and SQL Server.

Revision ID: kb_0019
Revises: kb_0018
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0019"
down_revision = "kb_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_items", sa.Column("lines", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kb_items") as b:
        b.drop_column("lines")
