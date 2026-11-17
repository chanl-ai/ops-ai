"""A thread's owner in its own column, and the lease and timer writes the runtime role makes

Revision ID: 0105_thread_owner_column
Revises: 0104_runtime_tables_isolated

graph_threads kept the person a thread belongs to only inside its meta JSON (`ownerEmail`), so every list or count by
owner read the JSON of each row. `owner` holds the same email, backfilled from the JSON and indexed by tenant and
owner; the store writes both wherever it writes the JSON.

Each owned thread's id and owner are copied into a session table in one transaction that sets graph_threads' policy
aside; the rows are then filled BATCH at a time, each batch committed alone with the policy set aside only inside it
(on SQL Server dropped and made again in the batch's transaction), so no lock lasts the whole fill. A last transaction
fills threads written meanwhile. Runs again after a stopped run.

The leases and timers stores now run inside the runtime role's transactions (install scope) rather than as the login,
so on PostgreSQL ops_runtime_tenant gains the writes they make: INSERT on thread_leases (it had SELECT and UPDATE for
the fence check, 0021) and SELECT, INSERT, UPDATE on timers. SQL Server's runtime user already holds them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.dialect import json_text
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, backfill_ddl, mssql_quiet_batch, session_table_ddl

revision = "0105_thread_owner_column"
down_revision = "0104_runtime_tables_isolated"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
INDEX = "ix_graph_threads_owner"
# Rows per committed batch; under 5000, where SQL Server escalates row locks to a table lock.
BATCH = 4000


def _threads() -> sa.Table:
    """graph_threads as far as the backfill needs, as of this revision."""
    return sa.Table(
        "graph_threads",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        sa.Column("meta", sa.JSON),
        sa.Column("owner", sa.String(320)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _has_owner() -> bool:
    """Whether a stopped run already added the column; offline SQL starts from 0104, where it is absent."""
    if op.get_context().as_sql:
        return False
    return "owner" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("graph_threads")}


def _fill(dialect: str, copy: str, before: list[str], after: list[str]) -> str:
    """Fills `owner` from the copy BATCH rows at a time, each batch committed on its own with graph_threads' policy set
    aside inside it. Only threads still without an owner whose copy holds one are taken, so each batch makes progress
    and the loop ends."""
    if dialect == "mssql":
        aside = "\n".join(f"    EXEC (N'{s.replace(chr(39), chr(39) * 2)}');" for s in before)
        back = "\n".join(f"    EXEC (N'{s.replace(chr(39), chr(39) * 2)}');" for s in after)
        return mssql_quiet_batch(
            f"DECLARE @n int;\nWHILE 1 = 1\nBEGIN\n    BEGIN TRANSACTION;\n{aside}\n"
            f"    UPDATE TOP ({BATCH}) g SET owner = s.v FROM graph_threads g JOIN {copy} s ON s.k = g.id "
            f"WHERE g.owner IS NULL;\n    SET @n = @@ROWCOUNT;\n{back}\n    COMMIT;\n    IF @n = 0 BREAK;\nEND"
        )
    # The policy is back before each COMMIT, the last batch's (which finds nothing) included.
    aside = "".join(f"        {s};\n" for s in before)
    back = "".join(f"        {s};\n" for s in after)
    return (
        f"DO $$\nDECLARE n integer;\nBEGIN\n    LOOP\n{aside}"
        f"        UPDATE graph_threads g SET owner = s.v FROM {copy} s WHERE s.k = g.id AND g.ctid IN "
        f"(SELECT x.ctid FROM graph_threads x JOIN {copy} y ON y.k = x.id WHERE x.owner IS NULL LIMIT {BATCH});\n"
        f"        GET DIAGNOSTICS n = ROW_COUNT;\n{back}"
        "        COMMIT;\n        EXIT WHEN n = 0;\n    END LOOP;\nEND $$"
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if op.get_context().as_sql and dialect == "postgresql":
        # The DBA script cannot look, and a stop after its first transaction leaves the column behind: re-run from
        # the step's start, the column is added only where it is missing.
        op.execute("ALTER TABLE graph_threads ADD COLUMN IF NOT EXISTS owner VARCHAR(320)")
    elif not _has_owner():
        with op.batch_alter_table("graph_threads") as b:
            b.add_column(sa.Column("owner", sa.String(320)))
    t = _threads()
    owner = json_text(t.c.meta, "ownerEmail")
    # Every tenant's threads are filled, so graph_threads' own policy is set aside, only ever inside a transaction.
    before, after = backfill_ddl([t], dialect, chain=CHAIN)
    if dialect in ("postgresql", "mssql"):
        copy_name = "#thread_owners_0105" if dialect == "mssql" else "thread_owners_0105"
        copy = sa.table(copy_name, sa.column("k"), sa.column("v"))
        for statement in before:
            op.execute(statement)
        op.execute(session_table_ddl(copy_name, dialect, [("k", 64), ("v", 320)]))
        op.execute(
            sa.insert(copy).from_select(
                ["k", "v"], sa.select(t.c.id, owner).where(t.c.owner.is_(None), owner.is_not(None))
            )
        )
        for statement in after:
            op.execute(statement)
        with op.get_context().autocommit_block():
            op.execute(_fill(dialect, copy_name, before, after))
        op.execute(f"DROP TABLE {copy_name}")
    for statement in before:
        op.execute(statement)
    op.execute(sa.update(t).where(t.c.owner.is_(None), owner.is_not(None)).values(owner=owner))
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
