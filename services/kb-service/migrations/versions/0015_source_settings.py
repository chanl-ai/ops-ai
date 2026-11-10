"""Each source keeps its own settings, and each item what it was indexed with

kb_sources.settings holds the source's reading, cleaning, splitting, rules and metadata settings (null: its kind's
defaults). kb_items.indexed_with is the digest of the settings an item's pieces were built under, so a change splits
again only items built under other settings. kb_runs gains when a run finished and who asked to cancel it, so a
rebuild in the background shows as running and can be stopped. Runs on PostgreSQL and SQL Server.

Revision ID: kb_0015
Revises: kb_0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0015"
down_revision = "kb_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_sources", sa.Column("settings", sa.JSON(), nullable=True))
    op.add_column("kb_items", sa.Column("indexed_with", sa.String(32), nullable=True))
    op.add_column("kb_runs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("kb_runs", sa.Column("cancelled_by", sa.String(200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kb_runs") as b:
        b.drop_column("cancelled_by")
        b.drop_column("finished_at")
    with op.batch_alter_table("kb_items") as b:
        b.drop_column("indexed_with")
    with op.batch_alter_table("kb_sources") as b:
        b.drop_column("settings")
