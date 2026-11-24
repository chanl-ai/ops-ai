"""Join the platform chain's heads from the branches taken into this integration branch

Revision ID: 20261124_2055_merge_heads
Revises: 20261124_0100_watches_cells, 20261124_0900_self_approve_reset

Changes no table: each branch added its own revision after the same earlier one, and Alembic needs one head to
upgrade.
"""

from __future__ import annotations

revision = "20261124_2055_merge_heads"
down_revision = ("20261124_0100_watches_cells", "20261124_0900_self_approve_reset")
branch_labels = None
depends_on = None

CHAIN = "platform"


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
