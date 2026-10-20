"""storage settings, credentials and their audit (c-100)

Revision ID: files_0003
Revises: files_0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "files_0003"
down_revision = "files_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_settings",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(length=320), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "storage_credentials",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("sealed", sa.Text(), nullable=False),
        sa.Column("set_by", sa.String(length=320), nullable=False),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "name"),
    )
    op.create_table(
        "storage_settings_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=320), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_storage_settings_audit_tenant", "storage_settings_audit", ["tenant_id", "at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_storage_settings_audit_tenant", table_name="storage_settings_audit")
    op.drop_table("storage_settings_audit")
    op.drop_table("storage_credentials")
    op.drop_table("storage_settings")
