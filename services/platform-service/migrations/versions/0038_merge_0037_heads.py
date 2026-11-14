"""join the three 0037 grid revisions into one head

The mcp, builder-connection and evals cells were each added on their own branch after 0036, so the tree had three
heads and `alembic upgrade head` refused to choose. Each one only adds its own grid cells and raises the permission
version, so they run in any order; this revision makes them one line again. Nothing to upgrade or downgrade.

Revision ID: 0038_merge_0037_heads
Revises: 0037_mcp_cells, 0037_builder_connections, 0037_evals_cells
"""

from __future__ import annotations

revision = "0038_merge_0037_heads"
down_revision = ("0037_mcp_cells", "0037_builder_connections", "0037_evals_cells")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
