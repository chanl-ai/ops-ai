"""Template copies keep the type version they made

Revision ID: documents_0015
Revises: documents_0014

A copy records the document type version it made (1 at the add, the new version at each update taken), so taking a
template's update can tell a type the team gave a version of its own since, and ask before leaving those edits out.
Nullable: copies made before carry none, and read as edited. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0015"
down_revision = "documents_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents_template_copies") as b:
        b.add_column(sa.Column("record_version", sa.Integer))


def downgrade() -> None:
    with op.batch_alter_table("documents_template_copies") as b:
        b.drop_column("record_version")
