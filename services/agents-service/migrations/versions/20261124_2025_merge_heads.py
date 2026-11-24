"""Join the agents chain's heads from the branches taken into this integration branch

Revision ID: 20261124_2025_merge_heads
Revises: 20261124_0257_skill_owner_ids, 20261124_1100_agents_outbox

Changes no table: each branch added its own revision after the same earlier one, and Alembic needs one head to
upgrade.
"""

from __future__ import annotations

revision = "20261124_2025_merge_heads"
down_revision = ("20261124_0257_skill_owner_ids", "20261124_1100_agents_outbox")
branch_labels = None
depends_on = None

CHAIN = "agents"


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
