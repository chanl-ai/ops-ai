"""Drop publish_policies and its audit: the publish-review setting lives in platform-service's policies (c-214)

Revision ID: 0055_drop_publish_policies
Revises: 0054_drop_mailbox_deployments

publishReview is a workspace policy read live from platform-service (`GET /v1/policies/publishReview`); nothing reads
these tables any more. An agents migration touches agents-service's tables only: a saved document here is not copied
into another service's table, so a workspace that had one sets it again on Settings > Access (the default is major).
The downgrade recreates the empty tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0055_drop_publish_policies"
down_revision = "0054_drop_mailbox_deployments"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"
TABLES = ("publish_policies", "publish_policy_audit")


def upgrade() -> None:
    op.drop_table("publish_policy_audit")
    op.drop_table("publish_policies")


def downgrade() -> None:
    """The empty tables as 0038 made them (index, grants, tenant RLS), so 0038's downgrade still applies."""
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
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {TENANT_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
