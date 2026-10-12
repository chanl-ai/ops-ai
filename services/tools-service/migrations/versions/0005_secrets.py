"""tool secrets and their audit

Ciphertext only (AES-256-GCM, ops_tools.secrets.cipher); a value never reaches these tables.

Revision ID: tools_0005_secrets
Revises: tools_0004_egress
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0005_secrets"
down_revision = "tools_0004_egress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secret_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("tool", sa.String(length=120), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_secret_audit_tenant_id"), "secret_audit", ["tenant_id"], unique=False)
    op.create_table(
        "tool_secrets",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "name"),
    )


def downgrade() -> None:
    op.drop_table("tool_secrets")
    op.drop_index(op.f("ix_secret_audit_tenant_id"), table_name="secret_audit")
    op.drop_table("secret_audit")
