"""Changes can wait for review: FAQ drafts

kb_changes held only what a sync applied. It gains where a change came from (`origin`: sync, or faq for a drafted
question-and-answer pair), its review state (`status`: applied for a sync's change; pending, approved, rejected,
superseded or source_changed for a draft), the draft itself (`detail`: question, answer, quote and where the quote
sits) and who decided it and when. Existing rows are a sync's applied changes. Runs on PostgreSQL and SQL Server.

Revision ID: kb_0022
Revises: kb_0021
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0022"
down_revision = "kb_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_changes", sa.Column("origin", sa.String(16), nullable=False, server_default="sync"))
    op.add_column("kb_changes", sa.Column("status", sa.String(16), nullable=False, server_default="applied"))
    op.add_column("kb_changes", sa.Column("detail", sa.JSON(), nullable=True))
    op.add_column("kb_changes", sa.Column("decided_by", sa.String(200), nullable=True))
    op.add_column("kb_changes", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_kb_changes_item_origin", "kb_changes", ["tenant_id", "item_id", "origin"])


def downgrade() -> None:
    op.drop_index("ix_kb_changes_item_origin", table_name="kb_changes")
    with op.batch_alter_table("kb_changes") as b:
        b.drop_column("decided_at")
        b.drop_column("decided_by")
        b.drop_column("detail")
        b.drop_column("status")
        b.drop_column("origin")
