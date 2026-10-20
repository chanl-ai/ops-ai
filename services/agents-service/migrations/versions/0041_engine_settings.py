"""engine_settings: the workspace floor for extracted fields (c-157)

Revision ID: 0041_engine_settings
Revises: 0040_widget_key_expiry_audit

One row per tenant: the confidence below which an Extract from file step sends a field to a person, whatever the step
sets (default 0.8 when no row). Tenant RLS as on publish_policies (0038).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041_engine_settings"
down_revision = "0040_widget_key_expiry_audit"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "engine_settings",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("extraction_floor", sa.Float(), nullable=False),
        sa.Column("updated_by", sa.String(320), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON engine_settings TO {TENANT_ROLE}")
    op.execute("ALTER TABLE engine_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE engine_settings FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY engine_settings_tenant ON engine_settings "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS engine_settings_tenant ON engine_settings")
    op.drop_table("engine_settings")
