"""A reading names the PDF its Word file or deck was drawn into

With the converter on, a knowledge read draws a Word file or deck as a PDF once per content digest and keeps it in
files-service; this column names that file, so the document view shows it and a page picture is drawn from it. Null
for every other reading. Runs on PostgreSQL and SQL Server.

Revision ID: documents_0023
Revises: documents_0022
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0023"
down_revision = "documents_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents_readings", sa.Column("rendition_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("documents_readings", "rendition_id")
