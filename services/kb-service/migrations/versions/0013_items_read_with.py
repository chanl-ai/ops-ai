"""Knowledge items record how they were read

A file source's item is indexed from its reading in documents-service; read_with keeps the reader version and OCR
settings it was read with, so a change to either asks for a new reading. An item waiting for its reading has status
"reading" (the column is free text). Runs on PostgreSQL and SQL Server.

Revision ID: kb_0013
Revises: kb_0012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0013"
down_revision = "kb_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_items", sa.Column("read_with", sa.String(120)))


def downgrade() -> None:
    with op.batch_alter_table("kb_items") as b:
        b.drop_column("read_with")
