"""poll_cursors: where each polled source stands, today a workflow's Email received trigger (c-187)

Revision ID: 0045_poll_cursors
Revises: 0044_team_default_agent

Tenant RLS as on engine_settings (0041). The mailbox listener runs outside any request and finds live workflows in
every tenant, so ops_runtime_system (BYPASSRLS) may also read engine_definitions; it writes nothing there.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_poll_cursors"
down_revision = "0044_team_default_agent"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"


def upgrade() -> None:
    op.create_table(
        "poll_cursors",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("binding_id", sa.String(80), primary_key=True),
        sa.Column("source", sa.String(320), nullable=False),
        sa.Column("folder", sa.String(200), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute(
        f"DO $$ BEGIN CREATE ROLE {SYSTEM_ROLE} NOLOGIN BYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON poll_cursors TO {TENANT_ROLE}")
    op.execute("ALTER TABLE poll_cursors ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE poll_cursors FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY poll_cursors_tenant ON poll_cursors "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )
    op.execute(f"GRANT SELECT ON engine_definitions TO {SYSTEM_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE SELECT ON engine_definitions FROM {SYSTEM_ROLE}")
        op.execute("DROP POLICY IF EXISTS poll_cursors_tenant ON poll_cursors")
    op.drop_table("poll_cursors")
