"""A reading's page remembers how often its picture was refused for a reason that passes

A page whose picture a model refused while busy or over today's limit is described again later, alone, without reading
the file again; the count stops it after a few tries. Null means the page is settled. Runs on PostgreSQL and SQL
Server.

Revision ID: documents_0021
Revises: documents_0020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0021"
down_revision = "documents_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents_reading_pages", sa.Column("picture_retries", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents_reading_pages", "picture_retries")
