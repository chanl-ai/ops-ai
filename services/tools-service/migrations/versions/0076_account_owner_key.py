"""owner_key: an account name is unique within its owner

A person's own account (origin "person") and a team account of one app could not share a name, so a person who wanted
to call their account "EU desk" was refused when the team already had one, whether or not they had connected it. Each
row now carries its owner (empty for the team, the person for their own account) and the unique name index holds one
name per app per owner.

Revision ID: tools_0076_account_owner_key
Revises: tools_0075_call_client_id
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0076_account_owner_key"
down_revision = "tools_0075_call_client_id"
branch_labels = None
depends_on = None

INDEX = "uq_connections_account_key"


def _named() -> sa.TextClause:
    return sa.text("account_key IS NOT NULL")


def upgrade() -> None:
    op.drop_index(INDEX, table_name="connections")
    with op.batch_alter_table("connections") as b:
        b.add_column(sa.Column("owner_key", sa.String(200), nullable=False, server_default=""))
    t = sa.table(
        "connections",
        sa.column("origin", sa.String),
        sa.column("created_by", sa.String),
        sa.column("owner_key", sa.String),
    )
    bind = op.get_bind()
    for who in bind.execute(sa.select(t.c.created_by).where(t.c.origin == "person").distinct()).scalars():
        bind.execute(
            t.update()
            .where(t.c.origin == "person", t.c.created_by == who)
            .values(owner_key=str(who or "").strip().casefold())
        )
    op.create_index(
        INDEX,
        "connections",
        ["tenant_id", "team_id", "app_id", "owner_key", "account_key"],
        unique=True,
        postgresql_where=_named(),
        mssql_where=_named(),
        sqlite_where=_named(),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="connections")
    with op.batch_alter_table("connections") as b:
        b.drop_column("owner_key")
    op.create_index(
        INDEX,
        "connections",
        ["tenant_id", "team_id", "app_id", "account_key"],
        unique=True,
        postgresql_where=_named(),
        mssql_where=_named(),
        sqlite_where=_named(),
    )
