"""trigger_events: what a workflow's trigger received and the run each started or why none (c-201)

Revision ID: 0056_trigger_events
Revises: 0055_drop_publish_policies

Tenant RLS as on cases (0053). Rows are only ever added, so the runtime role may select and insert.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0056_trigger_events"
down_revision = "0055_drop_publish_policies"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "trigger_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("workflow_id", sa.String(200), nullable=False),
        sa.Column("source", sa.String(320), nullable=False),
        sa.Column("event_key", sa.String(200), nullable=False),
        sa.Column("sender", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("received_at", sa.String(40), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("run_id", sa.String(64)),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_trigger_events_workflow", "trigger_events", ["tenant_id", "workflow_id", "recorded_at"])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute(f"GRANT SELECT, INSERT ON trigger_events TO {TENANT_ROLE}")
    op.execute("ALTER TABLE trigger_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE trigger_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY trigger_events_tenant ON trigger_events "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS trigger_events_tenant ON trigger_events")
    op.drop_index("ix_trigger_events_workflow", table_name="trigger_events")
    op.drop_table("trigger_events")
