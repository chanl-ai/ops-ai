"""Delete the stored v1 mailbox deployments, their cursors and their message ledger (c-212)

Revision ID: 0054_drop_mailbox_deployments
Revises: 0053_cases

The mailbox channel and its poll route are gone: mail starts workflows through the Email received trigger, which keeps
its own cursors (poll_cursors, 0045). A stored `mailbox` deployment could never run again, and its ledger rows key a
thread no route reads. Widget, API and MCP deployments are kept. The downgrade cannot bring the deleted rows back.
"""

from __future__ import annotations

from alembic import op

revision = "0054_drop_mailbox_deployments"
down_revision = "0053_cases"
branch_labels = None
depends_on = None

MAILBOX = "SELECT id FROM deployments WHERE channel = 'mailbox'"


def upgrade() -> None:
    op.execute(f"DELETE FROM channel_messages WHERE deployment_id IN ({MAILBOX})")
    op.execute(f"DELETE FROM channel_cursors WHERE deployment_id IN ({MAILBOX})")
    op.execute("DELETE FROM deployments WHERE channel = 'mailbox'")


def downgrade() -> None:
    """Nothing to restore: the rows were for a channel that no longer exists."""
