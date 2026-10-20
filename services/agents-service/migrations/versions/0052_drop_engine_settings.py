"""Drop engine_settings: the extraction floor is platform-service's `extractionFloor` policy

Revision ID: 0052_drop_engine_settings
Revises: 0051_drop_registry_owner

The worker reads the floor from Govern > Policies (platform-service), which the console already edits; this table was a
second copy the console never wrote. A floor set here is not carried over: the policy's default (0.8) applies until an
admin sets it in Govern > Policies.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0052_drop_engine_settings"
down_revision = "0051_drop_registry_owner"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS engine_settings_tenant ON engine_settings")
    op.drop_table("engine_settings")


def downgrade() -> None:
    op.create_table(
        "engine_settings",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("extraction_floor", sa.Float(), nullable=False),
        sa.Column("updated_by", sa.String(320), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON engine_settings TO {TENANT_ROLE}")
    op.execute("ALTER TABLE engine_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE engine_settings FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY engine_settings_tenant ON engine_settings "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )
