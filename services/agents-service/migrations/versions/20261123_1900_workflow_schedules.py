"""workflow_schedules: one saved schedule per workflow and trigger step, with the schedule clock's slot state

Revision ID: 20261123_1900_workflow_schedules
Revises: 0120_model_call_reservations

Outside the workflow's versions, so a save applies at once (store/schedules.py). Tenant RLS as on poll_cursors (0045),
with team_id a plain column: a schedule is read and written through its workflow's own rights, which cover shared
workflows the team policy has no branch for. The runtime role may delete, because clearing a schedule and deleting its
workflow remove the row, and may delete trigger_events, because the schedule clock drops its own rows after
KEEP_SCHEDULE_DAYS (store/trigger_events.py).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261123_1900_workflow_schedules"
down_revision = "0120_model_call_reservations"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "workflow_schedules",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("workflow_id", sa.String(64), primary_key=True),
        sa.Column("trigger_step", sa.String(100), primary_key=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("rule", sa.JSON, nullable=False),
        sa.Column("changed_by", sa.String(200), nullable=False),
        sa.Column("changed_by_name", sa.String(200), nullable=True),
        sa.Column("changed_at", sa.String(32), nullable=False),
        sa.Column("rule_digest", sa.String(64), nullable=True),
        sa.Column("last_slot_at", sa.String(32), nullable=True),
        sa.Column("last_outcome", sa.String(16), nullable=True),
        sa.Column("last_run_id", sa.String(64), nullable=True),
        sa.Column("seen_at", sa.String(32), nullable=True),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_schedules TO {TENANT_ROLE}")
    op.execute("ALTER TABLE workflow_schedules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workflow_schedules FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY workflow_schedules_tenant ON workflow_schedules "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )
    op.execute(f"GRANT DELETE ON trigger_events TO {TENANT_ROLE}")
    # The grant is for the schedule clock's own rows: a restrictive policy leaves email trigger rows undeletable.
    op.execute(
        "CREATE POLICY trigger_events_schedule_delete ON trigger_events AS RESTRICTIVE FOR DELETE "
        "USING (source LIKE 'schedule:%')"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS trigger_events_schedule_delete ON trigger_events")
        op.execute(f"REVOKE DELETE ON trigger_events FROM {TENANT_ROLE}")
        op.execute("DROP POLICY IF EXISTS workflow_schedules_tenant ON workflow_schedules")
    op.drop_table("workflow_schedules")
