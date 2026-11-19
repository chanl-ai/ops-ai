"""A knowledge base keeps its answer, sync, access and source-default settings

kb_bases.settings holds the sections beside retrieval: what the base gives back and its no-answer message, how syncs
of its sources treat changes and removals, whether it is offered as an MCP tool, and how a new source splits. Null
reads as the defaults, and a base saved before keeps the answer shape and message its retrieval settings held, so no
row is rewritten here. Retrieval keys the base no longer keeps are left out when read and dropped on the next save.
Runs on PostgreSQL and SQL Server.

Revision ID: kb_0024
Revises: kb_0023
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0024"
down_revision = "kb_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_bases", sa.Column("settings", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kb_bases") as b:
        b.drop_column("settings")
