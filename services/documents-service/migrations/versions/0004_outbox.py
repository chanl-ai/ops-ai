"""service events documents-service reports (c-252, on c-258's outbox)

A person's correction writes extraction.corrected to `documents_outbox` in the transaction that records it; the relay
delivers it to agents-service, whose event workflow saves the corrected read on the file.

Revision ID: documents_0004
Revises: documents_0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0004"
down_revision = "documents_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents_outbox",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("event_key", sa.String(length=200), nullable=False),
        sa.Column("actor", sa.String(length=320), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Float(asdecimal=False), nullable=False),
        sa.Column("next_at", sa.Float(asdecimal=False), nullable=True),
        sa.Column("sent_at", sa.Float(asdecimal=False), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_outbox_due", "documents_outbox", ["sent_at", "next_at"])


def downgrade() -> None:
    pass
