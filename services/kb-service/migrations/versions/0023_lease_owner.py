"""A source's sync lease names who holds it

kb_sources.lease_owner is the holder's token: a sync or rebuild renews its own lease while it runs and releases only
its own, so a run that outlived its first lease never clears the lease of the run that took over. Runs on PostgreSQL
and SQL Server.

Revision ID: kb_0023
Revises: kb_0022
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0023"
down_revision = "kb_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_sources", sa.Column("lease_owner", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kb_sources") as b:
        b.drop_column("lease_owner")
