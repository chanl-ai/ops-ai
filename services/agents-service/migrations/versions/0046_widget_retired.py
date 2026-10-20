"""widget_deployments.retired_at: an embed retired for good (c-130)

Revision ID: 0046_widget_retired
Revises: 0045_poll_cursors

A retired embed stays listed for the record and answers no page again; a pause can be undone, a retire cannot. Null on
every embed made before, which reads as not retired.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0046_widget_retired"
down_revision = "0045_poll_cursors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("widget_deployments", sa.Column("retired_at", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("widget_deployments", "retired_at")
