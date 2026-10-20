"""widget mint keys expire, and creating or revoking one leaves an audit row (c-131 review)

Revision ID: 0040_widget_key_expiry_audit
Revises: 0039_widget_mint_keys

As platform keys: a key carries `expires_at` and mints nothing after it; who created or revoked which key, and when,
is kept in widget_mint_key_audit. Keys made before this have no expiry. Tenant RLS as on widget_mint_keys (0039).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040_widget_key_expiry_audit"
down_revision = "0039_widget_mint_keys"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.add_column("widget_mint_keys", sa.Column("expires_at", sa.String(32)))
    op.create_table(
        "widget_mint_key_audit",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="local", index=True),
        sa.Column("deployment_id", sa.String(64), nullable=False, index=True),
        sa.Column("key_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(320), nullable=False),
        sa.Column("at", sa.String(32), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, INSERT ON widget_mint_key_audit TO {TENANT_ROLE}")
        op.execute("ALTER TABLE widget_mint_key_audit ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE widget_mint_key_audit FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY widget_mint_key_audit_tenant ON widget_mint_key_audit "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    op.drop_table("widget_mint_key_audit")
    op.drop_column("widget_mint_keys", "expires_at")
