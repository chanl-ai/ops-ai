"""team_default_agents: the agent a team's new chats start on (c-174)

Revision ID: 0044_team_default_agent
Revises: 0043_agent_template

One row per tenant and team. Provisioning (c-175) writes the first row when it makes a team's first agent; a team admin
changes it after that. No row means the team has no default, and a chat started without an agent is refused. Tenant RLS
as on engine_settings (0041).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044_team_default_agent"
down_revision = "0043_agent_template"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    op.create_table(
        "team_default_agents",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64), primary_key=True),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("updated_by", sa.String(320), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DO $$ BEGIN CREATE ROLE {TENANT_ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON team_default_agents TO {TENANT_ROLE}")
    op.execute("ALTER TABLE team_default_agents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE team_default_agents FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY team_default_agents_tenant ON team_default_agents "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS team_default_agents_tenant ON team_default_agents")
    op.drop_table("team_default_agents")
