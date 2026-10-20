"""idempotency keys for uploads

Revision ID: files_0002
Revises: files_0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "files_0002"
down_revision = "files_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_idempotency",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "key_hash"),
    )
    op.create_index("ix_file_idempotency_file", "file_idempotency", ["tenant_id", "file_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_file_idempotency_file", table_name="file_idempotency")
    op.drop_table("file_idempotency")
