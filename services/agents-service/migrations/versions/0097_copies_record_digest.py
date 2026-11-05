"""Template copies keep the digest of the record they made

Revision ID: 0097_copies_record_digest
Revises: 0096_system_reads_team_defaults

A copy records the digest of its own record as the copy made it, so taking a template's update can tell a copy the
team edited since and ask before replacing those edits. Nullable: copies made before carry none, and read as edited.
Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0097_copies_record_digest"
down_revision = "0096_system_reads_team_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("template_copies") as b:
        b.add_column(sa.Column("record_digest", sa.String(64)))


def downgrade() -> None:
    with op.batch_alter_table("template_copies") as b:
        b.drop_column("record_digest")
