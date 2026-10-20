"""task_assists: what task assist wrote for a typed task when its step paused (c-302)

A reviewer read every region of a task to find what was asked and what was in doubt. With task assist on, one model
call writes the question, a summary, the doubtful fields and a suggested action when the step pauses, kept here so a
task costs one call however often it is read; tenant RLS as on task_types (0063).

Revision ID: 0064_task_assists
Revises: 0063_task_types
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0064_task_assists"
down_revision = "0063_task_types"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "task_assists",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("step_id", sa.String(200), primary_key=True),
        sa.Column("assist", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute(f"GRANT SELECT, INSERT ON task_assists TO {TENANT_ROLE}")
    op.execute("ALTER TABLE task_assists ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE task_assists FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY task_assists_tenant ON task_assists "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS task_assists_tenant ON task_assists")
    op.drop_table("task_assists")
