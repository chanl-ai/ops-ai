"""an account's model provider keys live in models-service (owner, 2026-10-27; c-509)

Revision ID: models_0007
Revises: models_0006

Provider keys were workspace-wide tool secrets read through tools-service. Every tool secret now belongs to one team
and never leaves for another service, so the account's provider keys get their own table here, sealed with the same
cipher, set by account admins and read by this service alone. Nothing is copied: a key saved in tools-service's
Secrets is saved again on Settings > Model providers (all existing data is test data, owner 2026-10-26).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.dialect import db_now

revision = "models_0007"
down_revision = "models_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_keys",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(120), primary_key=True),
        sa.Column("ciphertext", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now()),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("provider_keys")
