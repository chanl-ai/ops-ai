"""widget_mint_keys: the per-deployment key a bank's server mints widget sessions with (c-131)

Revision ID: 0039_widget_mint_keys
Revises: 0038_publish_policies

Replaces the team API key for minting: a key mints for one deployment and nothing else. Tenant RLS as on
widget_deployments (0035). Only the secret's SHA-256 is stored.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039_widget_mint_keys"
down_revision = "0038_publish_policies"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "widget_mint_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="local", index=True),
        sa.Column("deployment_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("last_used_at", sa.String(32)),
        sa.Column("revoked_at", sa.String(32)),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON widget_mint_keys TO {TENANT_ROLE}")
        op.execute("ALTER TABLE widget_mint_keys ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE widget_mint_keys FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY widget_mint_keys_tenant ON widget_mint_keys "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    op.drop_table("widget_mint_keys")
