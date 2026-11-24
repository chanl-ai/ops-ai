"""Join the files chain's heads from the branches taken into this integration branch

Revision ID: 20261124_2041_merge_heads
Revises: files_0017, 20261126_0900_watch_event_links

Changes no table: each branch added its own revision after the same earlier one, and Alembic needs one head to
upgrade.
"""

from __future__ import annotations

revision = "20261124_2041_merge_heads"
down_revision = ("files_0017", "20261126_0900_watch_event_links")
branch_labels = None
depends_on = None

CHAIN = "files"


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
