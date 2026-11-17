"""Keep a reviewer's reason with a decided change

An approval or rejection of a held change may carry a short reason. The column is nullable with no default, so
existing rows stay null and nothing is backfilled. Runs on PostgreSQL and SQL Server.

Revision ID: kb_0029
Revises: kb_0028
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0029"
down_revision = "kb_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_changes", sa.Column("decision_reason", sa.String(500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kb_changes") as b:
        b.drop_column("decision_reason")
