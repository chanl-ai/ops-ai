"""widget_deployments: an agent's chat served to pages on other origins, pinned to a published version (c-117)

Revision ID: 0035_widget_deployments
Revises: 0034_skill_created_by

Tenant RLS as on the run tables (0021).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_widget_deployments"
down_revision = "0034_skill_created_by"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "widget_deployments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="local", index=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("agent_version", sa.Integer, nullable=False),
        sa.Column("origins", sa.JSON, nullable=False),
        sa.Column("paused", sa.Boolean, nullable=False),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON widget_deployments TO {TENANT_ROLE}")
        op.execute("ALTER TABLE widget_deployments ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE widget_deployments FORCE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY widget_deployments_tenant ON widget_deployments "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    op.drop_table("widget_deployments")
