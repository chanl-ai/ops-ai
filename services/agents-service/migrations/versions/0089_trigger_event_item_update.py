"""The runtime role may clear a set-aside email's kept copy (c-561)

Revision ID: 0089_trigger_event_item_update
Revises: 0088_trigger_event_item

Trigger events are only ever added, so the runtime role was granted SELECT and INSERT. A set-aside email's kept copy
is cleared once Run again starts its run, or after 30 days, so the role may update that one column and no other: the
rest of an event still cannot change. SQL Server's grants already allow it.
"""

from __future__ import annotations

from alembic import op

revision = "0089_trigger_event_item_update"
down_revision = "0088_trigger_event_item"
branch_labels = None
depends_on = None

TENANT_ROLE = "ops_runtime_tenant"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT UPDATE (item) ON trigger_events TO {TENANT_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE UPDATE (item) ON trigger_events FROM {TENANT_ROLE}")
