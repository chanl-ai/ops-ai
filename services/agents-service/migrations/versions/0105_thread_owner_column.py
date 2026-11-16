"""A thread's owner in its own column, and the lease and timer writes the runtime role makes

Revision ID: 0105_thread_owner_column
Revises: 0104_runtime_tables_isolated

graph_threads kept the person a thread belongs to only inside its meta JSON (`ownerEmail`), so every list or count by
owner read the JSON of each row. `owner` holds the same email, backfilled from the JSON and indexed by tenant and
owner; the store writes both wherever it writes the JSON.

The leases and timers stores now run inside the runtime role's transactions (install scope) rather than as the login,
so on PostgreSQL ops_runtime_tenant gains the writes they make: INSERT on thread_leases (it had SELECT and UPDATE for
the fence check, 0021) and SELECT, INSERT, UPDATE on timers. SQL Server's runtime user already holds them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.dialect import json_text
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, backfill_ddl

revision = "0105_thread_owner_column"
down_revision = "0104_runtime_tables_isolated"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
INDEX = "ix_graph_threads_owner"


def _threads() -> sa.Table:
    """graph_threads as far as the backfill needs, as of this revision."""
    return sa.Table(
        "graph_threads",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        sa.Column("meta", sa.JSON),
        sa.Column("owner", sa.String(320)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    with op.batch_alter_table("graph_threads") as b:
        b.add_column(sa.Column("owner", sa.String(320)))
    t = _threads()
    # Every tenant's threads are filled, so graph_threads' own policy is set aside for the backfill.
    before, after = backfill_ddl([t], dialect, chain=CHAIN)
    for statement in before:
        op.execute(statement)
    op.execute(sa.update(t).values(owner=json_text(t.c.meta, "ownerEmail")))
    for statement in after:
        op.execute(statement)
    op.create_index(INDEX, "graph_threads", ["tenant_id", "owner"])
    if dialect == "postgresql":
        op.execute(f"GRANT INSERT ON thread_leases TO {TENANT_ROLE}")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON timers TO {TENANT_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE SELECT, INSERT, UPDATE ON timers FROM {TENANT_ROLE}")
        op.execute(f"REVOKE INSERT ON thread_leases FROM {TENANT_ROLE}")
    op.drop_index(INDEX, "graph_threads")
    with op.batch_alter_table("graph_threads") as b:
        b.drop_column("owner")
