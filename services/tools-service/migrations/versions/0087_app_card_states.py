"""app_cards: the state, sign-in and own account of each card, so the Apps tabs and filters run in SQL

GET /v1/apps filtered nothing: the console chose the Connected and Available tabs, the State and Category filters in
the browser, which a server page cannot. Each card row now holds its state as the team sees it, how its default account
signs in, the account a person's own sign-in decides it on, and when a team token's state lapses; category and kind
lead an index each for their filters.

No backfill: the columns start empty and the service's card stamp names the rows' shape, so every team's rows are
rebuilt on its first list after this release. Downgrade drops the indexes and the columns; none has a default.

Revision ID: tools_0087_app_card_states
Revises: tools_0086_module_tenant_policy
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0087_app_card_states"
down_revision = "tools_0086_module_tenant_policy"
branch_labels = None
depends_on = None

TABLE = "app_cards"
COLUMNS = (
    sa.Column("state", sa.String(24), nullable=True),
    sa.Column("sign_in", sa.String(16), nullable=True),
    sa.Column("own_account", sa.String(64), nullable=True),
    sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
)
INDEXES = {"ix_app_cards_category": "category", "ix_app_cards_kind": "kind"}


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column(TABLE, column.copy())
    for name, column in INDEXES.items():
        op.create_index(name, TABLE, ["tenant_id", "team_id", column])


def downgrade() -> None:
    for name in INDEXES:
        op.drop_index(name, table_name=TABLE)
    for column in reversed(COLUMNS):
        op.drop_column(TABLE, column.name)
