"""connection_tokens.test: the last test of each signed-in account, the team's or a person's own

An account reads connected once its sign-in succeeds; its test runs right after and its outcome ({status, message, at})
is kept on that account's row, so a failed test warns on the row it belongs to instead of blocking it.

Revision ID: tools_0060_account_test
Revises: tools_0059_connection_origin
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0060_account_test"
down_revision = "tools_0059_connection_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("connection_tokens") as b:
        b.add_column(sa.Column("test", sa.JSON))


def downgrade() -> None:
    with op.batch_alter_table("connection_tokens") as b:
        b.drop_column("test")
