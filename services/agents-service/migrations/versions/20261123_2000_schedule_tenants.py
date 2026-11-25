"""ops_runtime_system reads workflow_schedules' tenant: the schedule clock lists the tenants holding a schedule

Each minute the schedule clock visits every tenant with a saved schedule, including one whose only scheduled workflow
is paused, so it can mark that schedule idle and wait for the next slot on resume. It finds those tenants before it
knows one, as the retention sweep finds memories, so the BYPASSRLS role reads the tenant column only, and the clock
then works each tenant inside its own.

Revision ID: 20261123_2000_schedule_tenants
Revises: 20261123_1900_workflow_schedules
"""

from __future__ import annotations

from alembic import op

revision = "20261123_2000_schedule_tenants"
down_revision = "20261123_1900_workflow_schedules"
branch_labels = None
depends_on = None

SYSTEM_ROLE = "ops_runtime_system"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT (tenant_id) ON workflow_schedules TO {SYSTEM_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE SELECT (tenant_id) ON workflow_schedules FROM {SYSTEM_ROLE}")
