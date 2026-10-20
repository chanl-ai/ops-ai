"""engine_definitions: workflow definitions, schema version 2, for the workflow runner (packages/ops_engine)

Revision ID: 0023_engine_definitions
Revises: 0022_decision_step_up_ref

Beside graph_versions, never in it: every v1 reader of graph_versions parses its rows as v1 definitions. Tenant rows
with forced row-level security, as 0021 set for the run tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_engine_definitions"
down_revision = "0022_decision_step_up_ref"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "engine_definitions",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("workflow_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("definition", sa.JSON, nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.UniqueConstraint("tenant_id", "workflow_id", "digest", name="uq_engine_definitions_digest"),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT, INSERT ON engine_definitions TO {TENANT_ROLE}")
    op.execute("ALTER TABLE engine_definitions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE engine_definitions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY engine_definitions_tenant ON engine_definitions "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    op.drop_table("engine_definitions")
