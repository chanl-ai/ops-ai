"""The last Test connection on each connection (c-558)

`connections.health` holds what Test connection found: ok or failed, the environment, whose account signed the read
(own or team), when and by whom, its latency, and the status or code it failed with. Null until the first test.

Revision ID: tools_0038_connection_health
Revises: tools_0037_personal_sign_in
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0038_connection_health"
down_revision = "tools_0037_personal_sign_in"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("health", sa.JSON))


def downgrade() -> None:
    op.drop_column("connections", "health")
