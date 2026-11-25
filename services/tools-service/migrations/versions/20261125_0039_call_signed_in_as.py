"""Which login a call ran as, kept on its log row

A call on an app everyone uses with the team's login acts as that login for the person who asked. The log row kept
the person (`acting_for`) and that the team's sign-in signed it (`credential`), not which login that was, so an audit
read later could not say who acted in the app. `signed_in_as` is the login's name when the call ran (who signed it in,
else the account's name). Nullable, so existing rows read as before. The downgrade drops it.

Revision ID: 20261125_0039_call_signed_in_as
Revises: 20261123_0141_sign_in_last_used
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261125_0039_call_signed_in_as"
down_revision = "20261123_0141_sign_in_last_used"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gateway_calls", sa.Column("signed_in_as", sa.String(320), nullable=True))


def downgrade() -> None:
    op.drop_column("gateway_calls", "signed_in_as")
