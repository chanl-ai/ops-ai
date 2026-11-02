"""ops_runtime_system reads team_default_agents: the start-up catch-up of each team's Ops Assistant (c-616)

At start agents-service brings every team's Ops Assistant nobody changed to the declared one. It finds those teams by
their default agent before it knows a tenant, as the run reconciler finds runs, so the BYPASSRLS role reads the table
(only its tenant, team and agent columns are used), and then works each team inside its own tenant.

Revision ID: 0096_system_reads_team_defaults
Revises: 0095_run_started_by_approver
"""

from __future__ import annotations

from alembic import op

revision = "0096_system_reads_team_defaults"
down_revision = "0095_run_started_by_approver"
branch_labels = None
depends_on = None

SYSTEM_ROLE = "ops_runtime_system"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT ON team_default_agents TO {SYSTEM_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE SELECT ON team_default_agents FROM {SYSTEM_ROLE}")
