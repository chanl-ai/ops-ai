"""A knowledge base counts the changes to its name and colour

kb_bases.revision rises by one with each rename or recolour and once more when the base is deleted; the `kb.changed`
event carries it, so a service keeping a copy of the names applies a late or repeated event over nothing newer
(ops_store.copies). Existing bases start at 0. Runs on PostgreSQL and SQL Server.

Revision ID: kb_0025
Revises: kb_0024
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0025"
down_revision = "kb_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_bases", sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    # SQL Server holds the column's default as a constraint of its own, which has to go first.
    op.drop_column("kb_bases", "revision", mssql_drop_default=True)
