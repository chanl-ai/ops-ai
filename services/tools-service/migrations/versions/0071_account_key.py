"""account_key: one name per app's account in a team, held by the database

Steps, agents and chats pick an account by its name, so two accounts of one app in one team sharing a name made the
pick ambiguous, and the name was checked only in code, which two adds at the same moment both pass. Each row now keeps
its name case-folded (account_key), and a filtered unique index holds one per app in a team. The key is a stored column
because SQL Server has no index over an expression; the filter leaves unnamed rows out, which SQL Server would
otherwise hold equal. Existing rows that already share a name keep the oldest's name; each later one gets " (2)", " (3)"
appended, so the index can be made.

Revision ID: tools_0071_account_key
Revises: tools_0070_config_setting_modes
"""

from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "tools_0071_account_key"
down_revision = "tools_0070_config_setting_modes"
branch_labels = None
depends_on = None

INDEX = "uq_connections_account_key"


def upgrade() -> None:
    with op.batch_alter_table("connections") as b:
        b.add_column(sa.Column("account_key", sa.String(200)))
    t = sa.table(
        "connections",
        sa.column("tenant_id", sa.String),
        sa.column("id", sa.String),
        sa.column("team_id", sa.String),
        sa.column("app_id", sa.String),
        sa.column("account_name", sa.String),
        sa.column("account_key", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(t.c.tenant_id, t.c.id, t.c.team_id, t.c.app_id, t.c.account_name)
        .where(t.c.account_name.isnot(None))
        .order_by(t.c.created_at, t.c.id)
    ).all()
    seen: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for tenant, cid, team, app, name in rows:
        text = str(name).strip()
        if not text:
            continue
        taken = seen[(tenant, team, app)]
        kept, n = text, 1
        while kept.casefold() in taken:
            n += 1
            kept = f"{text} ({n})"
        taken.add(kept.casefold())
        bind.execute(
            t.update()
            .where(t.c.tenant_id == tenant, t.c.id == cid)
            .values(account_name=kept, account_key=kept.casefold())
        )
    named = sa.text("account_key IS NOT NULL")
    op.create_index(
        INDEX,
        "connections",
        ["tenant_id", "team_id", "app_id", "account_key"],
        unique=True,
        postgresql_where=named,
        mssql_where=named,
        sqlite_where=named,
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="connections")
    with op.batch_alter_table("connections") as b:
        b.drop_column("account_key")
