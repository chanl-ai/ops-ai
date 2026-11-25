"""When each sign-in was last used, and who ended it

Apps > People lists every person's sign-ins with when a call last signed with each, and an admin may end one. The
token row had neither: `last_used_at` is set by the call that signs with the row (at most once a minute), and
`ended_by` names the admin who ended the sign-in, beside `refused_reason` `ended_by_admin`. Both are nullable, so
existing rows read as never used and not ended. The downgrade drops them.

Revision ID: 20261123_0141_sign_in_last_used
Revises: 20261122_2038_list_sort_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261123_0141_sign_in_last_used"
down_revision = "20261122_2038_list_sort_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connection_tokens", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("connection_tokens", sa.Column("ended_by", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("connection_tokens", "ended_by")
    op.drop_column("connection_tokens", "last_used_at")
