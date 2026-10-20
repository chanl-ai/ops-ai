"""publish_policies and publish_policy_audit: which publishes need a second person's review (c-086)

Revision ID: 0038_publish_policies
Revises: 0037_deployment_team

One versioned JSON document per tenant, keyed by team and area, and an audit row per save. On PostgreSQL both tables
get the tenant policy the run tables have (0021): visible and writable only while `app.tenant_id` names the tenant.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_publish_policies"
down_revision = "0037_deployment_team"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"
TABLES = ("publish_policies", "publish_policy_audit")


def upgrade() -> None:
    op.create_table(
        "publish_policies",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("document", sa.Text, nullable=False),
        sa.Column("updated_by", sa.String(320), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "publish_policy_audit",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("actor", sa.String(320), nullable=False),
        sa.Column("at", sa.String(32), nullable=False),
    )
    op.create_index("ix_publish_policy_audit_tenant_id", "publish_policy_audit", ["tenant_id"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {TENANT_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
            op.execute(f"REVOKE ALL ON {table} FROM {TENANT_ROLE}")
    op.drop_index("ix_publish_policy_audit_tenant_id", table_name="publish_policy_audit")
    op.drop_table("publish_policy_audit")
    op.drop_table("publish_policies")
