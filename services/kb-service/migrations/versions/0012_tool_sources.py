"""Knowledge sources read through a connection's tools (c-564)

A "tool" source keeps what it reads from (the plugin, its two tools, the connection), where the last sync ended (its
watermark and saved cursor) and a lease so one source never syncs twice at once. An item read through it keeps the
system's change marker, the item it is attached to and its address in the system.

Revision ID: kb_0012
Revises: kb_0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0012"
down_revision = "kb_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_sources", sa.Column("config", sa.JSON))
    op.add_column("kb_sources", sa.Column("lease_until", sa.DateTime(timezone=True)))
    op.add_column("kb_items", sa.Column("marker", sa.String(120)))
    op.add_column("kb_items", sa.Column("parent_id", sa.String(64)))
    op.add_column("kb_items", sa.Column("url", sa.Text))


def downgrade() -> None:
    op.drop_column("kb_items", "url")
    op.drop_column("kb_items", "parent_id")
    op.drop_column("kb_items", "marker")
    op.drop_column("kb_sources", "lease_until")
    op.drop_column("kb_sources", "config")
