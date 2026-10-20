"""service events files-service reports, and read requests (c-250, on c-258's outbox)

A deleted file's file.deleted is written to `files_outbox` in the transaction that deletes it, and a person's read
request (`file_read_requests`) with its file.read_requested; a relay delivers each to agents-service, which starts the
system workflow that purges what was read from the file, or reads it and saves what was read.

Revision ID: files_0008
Revises: files_0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "files_0008"
down_revision = "files_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "files_outbox",
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
    op.create_index("ix_files_outbox_due", "files_outbox", ["sent_at", "next_at"])
    op.create_table(
        "file_read_requests",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("request_key", sa.String(length=200), nullable=False),
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("team", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=320), nullable=False),
        sa.Column("document_type_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("type_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "request_key"),
    )
    op.create_index("ix_file_read_requests_file", "file_read_requests", ["tenant_id", "file_id"])


def downgrade() -> None:
    pass
