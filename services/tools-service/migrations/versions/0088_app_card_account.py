"""app_cards: the default account of each card, so the Apps list filters on it in SQL

GET /v1/apps could not keep the cards that have an account: the console read on page after page and dropped the rest.
Each card row now holds its default account's id.

No backfill: the column starts empty and the service's card stamp names the rows' shape, so every team's rows are
rebuilt on its first list after this release. Downgrade drops the column; it has no default.

Revision ID: tools_0088_app_card_account
Revises: tools_0087_app_card_states
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0088_app_card_account"
down_revision = "tools_0087_app_card_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_cards", sa.Column("connection_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("app_cards", "connection_id")
