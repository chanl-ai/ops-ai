"""A set-aside email keeps the message for Run again (c-561)

Revision ID: 0088_trigger_event_item
Revises: 0087_run_reconciler

A message whose run fails to start on 3 reads is set aside so the mail after it is read. Its trigger event keeps the
message as read, so a person can run it again once the cause is fixed without the mailbox being read again. The copy
is cleared once its run starts or after 30 days. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0088_trigger_event_item"
down_revision = "0087_run_reconciler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trigger_events", sa.Column("item", sa.Text()))


def downgrade() -> None:
    op.drop_column("trigger_events", "item")
