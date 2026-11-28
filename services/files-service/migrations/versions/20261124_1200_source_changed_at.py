"""file_versions.source_changed_at: when the source changed the bytes a version holds

The file page says when the source last changed the file (SharePoint's modified time for the version Files holds),
which no column kept: a version kept only when Files wrote it. Null for uploads and for versions written before.

Revision ID: 20261124_1200_source_changed_at
Revises: 20261124_0010_file_watches
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261124_1200_source_changed_at"
down_revision = "20261124_0010_file_watches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("file_versions") as b:
        b.add_column(sa.Column("source_changed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("file_versions") as b:
        b.drop_column("source_changed_at")
