"""Each person's own sign-in on a connection, and the links that ask them for it (c-558)

`connections.sign_in` says whose account a call signs in with: `team` (the connection's one sign-in, as before),
`person` (the person the call acts for) or `person_or_team` (the person's, and the team's for a call with nobody
behind it when `team_backup` is on). `oauth_states.token_for` is the token row a sign-in fills: '' for the team's, a
person's id for their own.

`connect_links` are the links a call acting for someone who has not signed in hands back: one per ask, kept only as a
hash, bound to the person, team, connection and environment, spent once and valid fifteen minutes.

Revision ID: tools_0037_personal_sign_in
Revises: tools_0036_call_acting_for
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0037_personal_sign_in"
down_revision = "tools_0036_call_acting_for"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("sign_in", sa.String(16), nullable=False, server_default="team"))
    op.add_column("connections", sa.Column("team_backup", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("oauth_states", sa.Column("token_for", sa.String(200), nullable=False, server_default=""))
    op.create_table(
        "connect_links",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("connection_id", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("person_id", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("scopes", sa.Text, nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["tenant_id", "connection_id"], ["connections.tenant_id", "connections.id"], ondelete="CASCADE"
        ),
    )


def downgrade() -> None:
    op.drop_table("connect_links")
    op.drop_column("oauth_states", "token_for")
    op.drop_column("connections", "team_backup")
    op.drop_column("connections", "sign_in")
