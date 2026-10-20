"""policies: the stricter rules an admin switches on per workspace (c-186)

A tenant with no row has every policy at its open default (owner direction 2026-10-17), so no running workspace meets a
control it did not set. The table carries tenant_id under the same row-level security as 0001; changes are audited in
audit_entries.

Revision ID: 0011_policies
Revises: 0010_sign_in
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_policies"
down_revision = "0010_sign_in"
branch_labels = None
depends_on = None

TENANT = "ops_platform_tenant"


def upgrade() -> None:
    op.create_table(
        "policies",
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON(none_as_null=False), nullable=False),
        sa.Column("updated_by", sa.String(320), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON policies TO {TENANT}")
    op.execute("ALTER TABLE policies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE policies FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY policies_tenant ON policies "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS policies_tenant ON policies")
    op.drop_table("policies")
