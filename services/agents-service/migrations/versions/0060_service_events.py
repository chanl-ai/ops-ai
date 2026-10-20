"""service_events: a named event a service emitted, and the system workflow runs it started (c-258)

Revision ID: 0060_service_events
Revises: 0059_review_assignments

Services never call each other to act: one emits an event (`tool_access.requested`, `file.deleted`) with a key, and
the system workflows whose Event trigger names it run. One row per event and key, so a repeat is found, and the runs
it started; tenant RLS as on trigger_events (0056). `engine_definitions.system` marks a platform-owned workflow: only
the server sets it, only such a workflow is started by an event, and no team edits one. `engine_runs.started_via`
names the event that carried a person's request, so `created_by` stays the person's email for every rule that reads it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0060_service_events"
down_revision = "0059_review_assignments"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.add_column("engine_definitions", sa.Column("system", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("engine_runs", sa.Column("started_via", sa.String(200)))
    op.create_table(
        "service_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("event_key", sa.String(200), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(320)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("run_ids", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", "event_key", name="uq_service_events_key"),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON service_events TO {TENANT_ROLE}")
    op.execute("ALTER TABLE service_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE service_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY service_events_tenant ON service_events "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS service_events_tenant ON service_events")
    op.drop_table("service_events")
    op.drop_column("engine_runs", "started_via")
    op.drop_column("engine_definitions", "system")
