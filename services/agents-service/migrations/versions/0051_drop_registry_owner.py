"""registry_agents, registry_workflows: drop `owner`, read by nothing since c-171

Revision ID: 0051_drop_registry_owner
Revises: 0050_mailbox_sender

The owning team is `team_id`, taken from the token (c-171); `owner` was a free-text label that nothing reads. The
downgrade puts the column back holding the team id, as the last writes did.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0051_drop_registry_owner"
down_revision = "0050_mailbox_sender"
branch_labels = None
depends_on = None

TABLES = ("registry_agents", "registry_workflows")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as b:
            b.drop_column("owner")


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column("owner", sa.String(200), nullable=False, server_default=""))
        op.execute(sa.text(f"UPDATE {table} SET owner = team_id"))
