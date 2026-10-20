"""gateway_calls carries the tenant the call was made in, so every read is scoped to one tenant (c-057 T013,
security review: the log was filtered by module only, and a scope-all team read every tenant's calls)
Revision ID: tools_0015_calls_tenant
Revises: tools_0014_step_up
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0015_calls_tenant"
down_revision = "tools_0014_step_up"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gateway_calls", sa.Column("tenant_id", sa.String(64), nullable=True))
    op.create_index("ix_gateway_calls_tenant_id", "gateway_calls", ["tenant_id"])
    # Existing rows: the tenant of the module the call resolved to. A row on no known module stays null and is read
    # by nobody, never attributed to a tenant it may not belong to.
    op.execute(
        "UPDATE gateway_calls SET tenant_id = m.tenant_id FROM tool_modules m "
        "WHERE gateway_calls.module_id = m.id AND gateway_calls.tenant_id IS NULL"
    )


def downgrade() -> None:
    # Kept so the chain's revert-and-reapply test (tests/test_registry_store.py) still runs end to end.
    op.drop_index("ix_gateway_calls_tenant_id", table_name="gateway_calls")
    op.drop_column("gateway_calls", "tenant_id")
