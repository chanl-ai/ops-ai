"""gateway_calls.acting_for and credential: whom a call acted for and whose credential signed it (c-558)

`acting_for` is the email of the person a verified acting-for token named, null for a call with nobody behind it.
`credential` is `person` when the person's own sign-in signed the call, `team` for the team's, null when the call
needed none.

Revision ID: tools_0036_call_acting_for
Revises: tools_0035_secrets_per_team
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0036_call_acting_for"
down_revision = "tools_0035_secrets_per_team"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gateway_calls", sa.Column("acting_for", sa.String(320)))
    op.add_column("gateway_calls", sa.Column("credential", sa.String(16)))


def downgrade() -> None:
    op.drop_column("gateway_calls", "credential")
    op.drop_column("gateway_calls", "acting_for")
