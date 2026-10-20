"""a write with no thread is claimed once per tenant, step, tool and input (c-070 review)

Revision ID: tools_0016_threadless_once
Revises: tools_0015_calls_tenant

ux_gateway_calls_effect (0001) is unique on (thread_id, step, tool, input_hash), and PostgreSQL counts NULLs as
distinct, so a write sent with no thread (an agent call outside a graph run) was never deduplicated: the same approved
write sent twice acted twice. This index covers those rows; the tenant is in it because, unlike a thread, a step is
only unique within the caller's own runs.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0016_threadless_once"
down_revision = "tools_0015_calls_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ux_gateway_calls_effect_threadless",
        "gateway_calls",
        ["tenant_id", "step", "tool", "input_hash"],
        unique=True,
        postgresql_where=sa.text("effect AND thread_id IS NULL"),
    )


def downgrade() -> None:
    # Kept so the chain's revert-and-reapply test (tests/test_registry_store.py) still runs end to end.
    op.drop_index("ux_gateway_calls_effect_threadless", table_name="gateway_calls")
