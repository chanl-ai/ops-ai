"""deployments, channel message ledger, delta cursors, thread inbox, files stub, thread external keys (E6)

Revision ID: 0010_mailbox_channel
Revises: 0009_timer_claims
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_mailbox_channel"
down_revision = "0009_timer_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("graph_threads", sa.Column("external_key", sa.String(512), nullable=True))
    op.add_column("graph_threads", sa.Column("deployment_id", sa.String(64), nullable=True))
    op.add_column("graph_threads", sa.Column("parent_thread_id", sa.String(64), nullable=True))
    # Unique: find-or-create by external key is one insert that either wins or conflicts.
    op.create_unique_constraint("uq_graph_threads_external_key", "graph_threads", ["external_key"])
    op.create_index("ix_graph_threads_deployment_id", "graph_threads", ["deployment_id"])
    op.create_index("ix_graph_threads_parent_thread_id", "graph_threads", ["parent_thread_id"])
    op.create_table(
        "deployments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("graph", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("multitask", sa.String(16), nullable=False, server_default="enqueue"),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "channel_messages",
        sa.Column("deployment_id", sa.String(64), primary_key=True),
        sa.Column("message_key", sa.String(512), primary_key=True),
        sa.Column("thread_id", sa.String(64)),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON()),
        sa.Column("received_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "channel_cursors",
        sa.Column("deployment_id", sa.String(64), primary_key=True),
        sa.Column("delta_link", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "thread_inbox",
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("message_key", sa.String(512), primary_key=True),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("delivered_at", sa.String(32)),
    )
    op.create_table(
        "channel_files",
        sa.Column("file_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    for table in ("channel_files", "thread_inbox", "channel_cursors", "channel_messages", "deployments"):
        op.drop_table(table)
    op.drop_index("ix_graph_threads_parent_thread_id", "graph_threads")
    op.drop_index("ix_graph_threads_deployment_id", "graph_threads")
    op.drop_constraint("uq_graph_threads_external_key", "graph_threads", type_="unique")
    for column in ("parent_thread_id", "deployment_id", "external_key"):
        op.drop_column("graph_threads", column)
