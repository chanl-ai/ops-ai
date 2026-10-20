"""tool registry: modules, operations, versions, reviews, approvals

The tables behind /v1/tool-modules (ops_tools.store.modules). Keys lead with tenant_id, which the row-level security
arriving with ops_identity filters on.

Revision ID: tools_0002_registry
Revises: tools_0001_gateway
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0002_registry"
down_revision = "tools_0001_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_modules",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("system", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("owner_team", sa.String(length=120), nullable=False),
        sa.Column("owner_contacts", sa.JSON(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("auth", sa.JSON(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("egress_hosts", sa.JSON(), nullable=False),
        sa.Column("data_classification", sa.String(length=16), nullable=False),
        sa.Column("catalog_id", sa.String(length=64), nullable=True),
        sa.Column("connection_id", sa.String(length=64), nullable=True),
        sa.Column("reachable", sa.Boolean(), nullable=False),
        sa.Column("drift", sa.Boolean(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("pending", sa.JSON(), nullable=False),
        sa.Column("baseline", sa.JSON(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "name", name="ux_tool_modules_name"),
    )
    op.create_table(
        "module_approvals",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("module_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_name", sa.String(length=200), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("major", sa.Integer(), nullable=False),
        sa.Column("operations", sa.JSON(), nullable=False),
        sa.Column("constraints", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(length=200), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "module_id"], ["tool_modules.tenant_id", "tool_modules.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_index("ix_module_approvals_module", "module_approvals", ["tenant_id", "module_id"], unique=False)
    op.create_table(
        "module_operations",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("module_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("tool_id", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("access", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("masked_output", sa.JSON(), nullable=False),
        sa.Column("binding", sa.JSON(), nullable=True),
        sa.Column("rate_limit_per_min", sa.Integer(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("amount_max", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("stub", sa.JSON(), nullable=False),
        sa.Column("seed_calls24h", sa.Integer(), nullable=False),
        sa.Column("seed_error_rate", sa.Float(), nullable=False),
        sa.Column("seed_p95_ms", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "module_id"], ["tool_modules.tenant_id", "tool_modules.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "name", name="ux_module_operations_name"),
    )
    op.create_index("ix_module_operations_module", "module_operations", ["tenant_id", "module_id"], unique=False)
    op.create_table(
        "module_versions",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("module_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("major", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("pinned_by", sa.JSON(), nullable=False),
        sa.Column("reachability", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "module_id"], ["tool_modules.tenant_id", "tool_modules.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "module_id", "version", name="ux_module_versions_version"),
    )
    op.create_index("ix_module_versions_module", "module_versions", ["tenant_id", "module_id"], unique=False)
    op.create_table(
        "security_reviews",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("module_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("major", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "module_id"], ["tool_modules.tenant_id", "tool_modules.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_index("ix_security_reviews_module", "security_reviews", ["tenant_id", "module_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_security_reviews_module", table_name="security_reviews")
    op.drop_table("security_reviews")
    op.drop_index("ix_module_versions_module", table_name="module_versions")
    op.drop_table("module_versions")
    op.drop_index("ix_module_operations_module", table_name="module_operations")
    op.drop_table("module_operations")
    op.drop_index("ix_module_approvals_module", table_name="module_approvals")
    op.drop_table("module_approvals")
    op.drop_table("tool_modules")
