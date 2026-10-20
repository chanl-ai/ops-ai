"""task_assists rows are filled after they are recorded (c-302, tick 30)

Revision ID: 0068_task_assists_fill
Revises: 0067_publish_requests_tenant

A typed step's assist is recorded as pending at the pause and replaced by what the model wrote, or by the failure, once
the call returns beside the pause; the tenant role needs UPDATE for that second write.
"""

from __future__ import annotations

from alembic import op

revision = "0068_task_assists_fill"
down_revision = "0067_publish_requests_tenant"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT UPDATE ON task_assists TO {TENANT_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE UPDATE ON task_assists FROM {TENANT_ROLE}")
