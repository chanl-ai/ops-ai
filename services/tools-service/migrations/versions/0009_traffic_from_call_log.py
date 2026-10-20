"""operation traffic comes from gateway_calls: drop the seeded counters, index the call log by module and time

Revision ID: tools_0009_traffic
Revises: tools_0008_approval_team
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0009_traffic"
down_revision = "tools_0008_approval_team"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ("seed_calls24h", "seed_error_rate", "seed_p95_ms"):
        op.drop_column("module_operations", col)
    # The registry's 24-hour and 14-day traffic reads filter by module and created_at.
    op.create_index("ix_gateway_calls_module_created", "gateway_calls", ["module_id", "created_at"], if_not_exists=True)


def downgrade() -> None:
    # Kept so the chain's revert-and-reapply test (tests/test_registry_store.py) still runs end to end.
    op.drop_index("ix_gateway_calls_module_created", "gateway_calls", if_exists=True)
    op.add_column("module_operations", sa.Column("seed_calls24h", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("module_operations", sa.Column("seed_error_rate", sa.Float(), nullable=False, server_default="0"))
    op.add_column("module_operations", sa.Column("seed_p95_ms", sa.Integer(), nullable=False, server_default="0"))
