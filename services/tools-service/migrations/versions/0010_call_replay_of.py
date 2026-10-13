"""a replayed write names the call whose result it returned

Revision ID: tools_0010_replay_of
Revises: tools_0009_traffic
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0010_replay_of"
down_revision = "tools_0009_traffic"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gateway_calls", sa.Column("replay_of", sa.String(64), nullable=True))


def downgrade() -> None:
    # Kept so the chain's revert-and-reapply test (tests/test_registry_store.py) still runs end to end.
    op.drop_column("gateway_calls", "replay_of")
