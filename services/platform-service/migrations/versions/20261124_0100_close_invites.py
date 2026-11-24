"""A null invite expiry on every active member: an accepted invite is closed

An active member with an invite expiry now has a pending new invite (`TeamStore.reinvite`), which an SSO sign-in from
that invite may consume to link the member's person. Accepting an invite used to leave the expiry in place, so a
member who joined in the last seven days would read as invited again and their used link would link once more. This
clears the expiry on every active member, with the table's isolation policy set aside (`backfill_ddl`) so it sees
every tenant's rows. The token hashes stay, so a used link still reads as accepted. The downgrade changes nothing:
the old code never reads the expiry of an active member.

Revision ID: 20261124_0100_close_invites
Revises: 20261123_2330_identity_per_user
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.schema import TENANT_SCOPED, backfill_ddl

revision = "20261124_0100_close_invites"
down_revision = "20261123_2330_identity_per_user"
branch_labels = None
depends_on = None

CHAIN = "platform"

CLOSE = "UPDATE members SET invite_expires_at = NULL WHERE status = 'active' AND invite_expires_at IS NOT NULL"


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    table = sa.Table("members", sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)
    before, after = backfill_ddl([table], dialect, chain=CHAIN, kind="tenant")
    for statement in (*before, CLOSE, *after):
        op.execute(statement)


def downgrade() -> None:
    pass
