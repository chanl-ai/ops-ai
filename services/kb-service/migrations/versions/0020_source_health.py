"""Sources keep their health, and items how often they were found gone

kb_sources gains the time of its last good sync, since when it has been failing, and how many runs in a row failed,
so a list shows a source's health in one column and a second failure raises an alert. kb_items.gone_count counts the
syncs in a row an item answered gone (404 or 410); at two it is removed and its address tombstoned. Runs on PostgreSQL
and SQL Server.

Revision ID: kb_0020
Revises: kb_0019
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0020"
down_revision = "kb_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_sources", sa.Column("last_good_sync_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("kb_sources", sa.Column("failing_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("kb_sources", sa.Column("failures_in_row", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("kb_items", sa.Column("gone_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("kb_items") as b:
        b.drop_column("gone_count")
    with op.batch_alter_table("kb_sources") as b:
        b.drop_column("failures_in_row")
        b.drop_column("failing_since")
        b.drop_column("last_good_sync_at")
