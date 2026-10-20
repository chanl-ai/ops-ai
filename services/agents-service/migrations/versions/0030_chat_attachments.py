"""chat_attachments: metadata and capped parsed text of files attached to chat messages (c-071)

Revision ID: 0030_chat_attachments
Revises: 0029_graph_threads_overrides

The bytes are in an ops_storage object store, written by agents-service's interim chat file store
(activities/attachments.py `ChatFileStore`, `fl_` ids) until c-087 moves them to files-service; this holds who owns
each file, its type and size, and the text parsed at upload. Tenant RLS as on the run tables (0021).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_chat_attachments"
down_revision = "0029_graph_threads_overrides"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="local", index=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("owner_email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("mime", sa.String(127), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("pages", sa.JSON, nullable=False),
        sa.Column("truncated", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, INSERT ON chat_attachments TO {TENANT_ROLE}")
        op.execute("ALTER TABLE chat_attachments ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE chat_attachments FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY chat_attachments_tenant ON chat_attachments "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    op.drop_table("chat_attachments")
