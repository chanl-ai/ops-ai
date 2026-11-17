"""A thread's budget and its model-call ledger are held to the thread's tenant by the database

Revision ID: 0104_runtime_tables_isolated
Revises: 0103_eval_cases_runs

thread_budgets and model_call_records had no tenant column, so any statement that named a thread id read or wrote that
thread's budget and its recorded model responses whatever tenant asked. Each now carries the tenant of its thread and
the generated tenant policy, with no column default: the stores write the caller's tenant. Neither has a team column: a
budget and a call are reached only through their thread, whose own policy holds the team.

The column is added and each thread's tenant copied into a session table in one short transaction: the thread's own,
or, for a thread that is gone, the one tenant other than `local` its events name. The rows are then filled in batches
of BATCH, each committed alone, so no lock on the table lasts the whole fill. A row whose thread is in neither is
recorded spend no tenant can be named for: it moves, insert before delete and in batches, to the table's
`_unattributed` side table, marked system and granted to no tenant role, where operators can count it and no tenant
reads it. A last transaction does the same for rows written meanwhile. Runs on PostgreSQL and SQL Server, and again
after a stopped run; the down path moves the side tables' rows back.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.dialect import db_now
from ops_store.schema import (
    TEAM_OWNED,
    TENANT_SCOPED,
    backfill_ddl,
    isolation_ddl,
    isolation_drop_ddl,
    mssql_drop_default_ddl,
    mssql_predicates_ddl,
    session_table_ddl,
    system,
)

revision = "0104_runtime_tables_isolated"
down_revision = "0103_eval_cases_runs"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
LOCAL = "local"
# Each table and its key.
TABLES = {"thread_budgets": "thread_id", "model_call_records": "id"}
# Each table's side table, for the rows no tenant can be named for, and the columns it keeps (all but tenant_id).
SIDE = {"thread_budgets": "thread_budgets_unattributed", "model_call_records": "model_call_records_unattributed"}
# Rows per committed batch; under 5000, where SQL Server escalates row locks to a table lock.
BATCH = 4000
# ops_agents.store.model_calls.UNATTRIBUTED, the same value; a migration does not import the service.
UNATTRIBUTED = "unattributed rows kept from before tenancy: a thread gone and no other row naming its tenant (0104)"


def _side_columns(name: str) -> list[sa.Column[Any]]:
    if name == "thread_budgets":
        kept = [
            sa.Column("thread_id", sa.String(64), primary_key=True),
            sa.Column("max_calls", sa.Integer()),
            sa.Column("max_tokens", sa.BigInteger()),
            sa.Column("max_cost_micros", sa.BigInteger()),
            sa.Column("updated_at", sa.String(40), nullable=False),
        ]
    else:
        kept = [
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("thread_id", sa.String(64), nullable=False),
            sa.Column("run_id", sa.String(64)),
            sa.Column("step", sa.String(120), nullable=False),
            sa.Column("task", sa.String(200)),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("model_alias", sa.String(120), nullable=False),
            sa.Column("calls", sa.Integer(), nullable=False),
            sa.Column("input_tokens", sa.BigInteger(), nullable=False),
            sa.Column("output_tokens", sa.BigInteger(), nullable=False),
            sa.Column("cost_micros", sa.BigInteger(), nullable=False),
            sa.Column("latency_ms", sa.Integer()),
            sa.Column("request_hash", sa.String(64)),
            sa.Column("response", sa.JSON()),
            sa.Column("created_at", sa.String(40), nullable=False),
        ]
    return [*kept, sa.Column("moved_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now())]


def _kept(name: str) -> str:
    return ", ".join(c.name for c in _side_columns(name) if c.name != "moved_at")


def _marked(name: str) -> sa.Table:
    """The table as far as its isolation needs, as of this revision."""
    return sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _owned(name: str) -> sa.Table:
    return sa.Table(
        name,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _read() -> list[sa.Table]:
    """The policed tables the attribution reads: a thread, and the events of a thread that is gone."""
    return [_owned("graph_threads"), _owned("thread_events")]


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _has_tenant(name: str) -> bool:
    """Whether a stopped run already added the column; offline SQL starts from 0103, where none has it."""
    if op.get_context().as_sql:
        return False
    return "tenant_id" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(name)}


def _create_sides(dialect: str) -> None:
    """The side tables, once: a stopped run may have made them. The DBA script cannot look, so on PostgreSQL it says
    IF NOT EXISTS; SQL Server's offline script starts from 0103, where none exists."""
    offline = op.get_context().as_sql
    for name, side in SIDE.items():
        if not offline and sa.inspect(op.get_bind()).has_table(side):
            continue
        op.create_table(
            side, *_side_columns(name), info=system(UNATTRIBUTED), if_not_exists=offline and dialect == "postgresql"
        )


def _events_tenant(thread: str) -> str:
    """The one tenant other than `local` the events of `thread` name, else NULL (none, or several)."""
    return (
        f"(SELECT MIN(e.tenant_id) FROM thread_events e WHERE e.thread_id = {thread} AND e.tenant_id <> '{LOCAL}' "
        "HAVING COUNT(DISTINCT e.tenant_id) = 1)"
    )


def _copy(dialect: str) -> tuple[str, list[str]]:
    """The session table holding each thread's tenant, and the statements that fill it: a thread's own, then for a gone
    thread the one its events name."""
    copy = "#thread_tenants_0104" if dialect == "mssql" else "thread_tenants_0104"
    return copy, [
        session_table_ddl(copy, dialect, [("id", 64), ("tenant_id", 64)]),
        f"INSERT INTO {copy} (id, tenant_id) SELECT id, tenant_id FROM graph_threads",
        f"INSERT INTO {copy} (id, tenant_id) SELECT e.thread_id, MIN(e.tenant_id) FROM thread_events e "
        f"WHERE e.tenant_id <> '{LOCAL}' AND NOT EXISTS (SELECT 1 FROM graph_threads g WHERE g.id = e.thread_id) "
        "GROUP BY e.thread_id HAVING COUNT(DISTINCT e.tenant_id) = 1",
    ]


def _fill(dialect: str, copy: str, name: str, key: str) -> str:
    """Fills `name` from the copy BATCH rows at a time, each batch committed on its own."""
    if dialect == "mssql":
        return (
            f"WHILE 1 = 1\nBEGIN\n"
            f"    UPDATE TOP ({BATCH}) r SET tenant_id = s.tenant_id FROM {name} r JOIN {copy} s ON s.id = r.thread_id "
            f"WHERE r.tenant_id IS NULL;\n"
            f"    IF @@ROWCOUNT = 0 BREAK;\nEND"
        )
    return (
        f"DO $$\nDECLARE n integer;\nBEGIN\n    LOOP\n"
        f"        UPDATE {name} r SET tenant_id = s.tenant_id FROM {copy} s WHERE s.id = r.thread_id AND r.{key} IN "
        f"(SELECT x.{key} FROM {name} x JOIN {copy} y ON y.id = x.thread_id WHERE x.tenant_id IS NULL LIMIT {BATCH});\n"
        f"        GET DIAGNOSTICS n = ROW_COUNT;\n        EXIT WHEN n = 0;\n        COMMIT;\n    END LOOP;\nEND $$"
    )


def _move(dialect: str, copy: str, name: str, key: str) -> str:
    """Moves the rows of `name` whose thread has no tenant in the copy to its side table, BATCH at a time, each batch
    copied and then deleted from `name` and committed on its own. A row with no tenant whose thread is in the copy was
    written after the fill, and `_settle` gives it its tenant."""
    side, cols = SIDE[name], _kept(name)
    pick = (
        f"x.tenant_id IS NULL AND NOT EXISTS (SELECT 1 FROM {copy} c WHERE c.id = x.thread_id) "
        f"AND NOT EXISTS (SELECT 1 FROM {side} s WHERE s.{key} = x.{key})"
    )
    moved = f"r.tenant_id IS NULL AND EXISTS (SELECT 1 FROM {side} s WHERE s.{key} = r.{key})"
    if dialect == "mssql":
        return (
            f"DECLARE @n int = 1;\nWHILE @n > 0\nBEGIN\n"
            f"    INSERT INTO {side} ({cols}) SELECT TOP ({BATCH}) {cols} FROM {name} x WHERE {pick};\n"
            f"    SET @n = @@ROWCOUNT;\n"
            f"    DELETE r FROM {name} r WHERE {moved};\nEND"
        )
    return (
        f"DO $$\nDECLARE n integer;\nBEGIN\n    LOOP\n"
        f"        INSERT INTO {side} ({cols}) SELECT {cols} FROM {name} x WHERE {pick} LIMIT {BATCH};\n"
        f"        GET DIAGNOSTICS n = ROW_COUNT;\n"
        f"        DELETE FROM {name} r WHERE {moved};\n"
        f"        COMMIT;\n        EXIT WHEN n = 0;\n    END LOOP;\nEND $$"
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    _create_sides(dialect)
    for name in TABLES:
        if op.get_context().as_sql and dialect == "postgresql":
            # The DBA script cannot look, and a stop after its first transaction leaves the column behind: re-run
            # from the step's start, the column is added only where it is missing.
            op.execute(f"ALTER TABLE {name} ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64)")
        elif not _has_tenant(name):
            op.add_column(name, sa.Column("tenant_id", sa.String(64), nullable=True))
    if dialect not in ("postgresql", "mssql"):
        _settle(dialect)
        return
    # graph_threads' and thread_events' policies are set aside only inside a transaction, never across a commit.
    copy, statements = _copy(dialect)
    before, after = backfill_ddl(_read(), dialect, chain=CHAIN)
    for statement in [*before, *statements, *after]:
        op.execute(statement)
    with op.get_context().autocommit_block():
        for name, key in TABLES.items():
            op.execute(_fill(dialect, copy, name, key))
            op.execute(_move(dialect, copy, name, key))
    op.execute(f"DROP TABLE {copy}")
    _settle(dialect)
    if dialect == "mssql":
        tables = [_marked(t) for t in TABLES]
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    for name in TABLES:
        if dialect == "postgresql":
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {TENANT_ROLE}")
        for statement in isolation_ddl(_marked(name), dialect, chain=CHAIN):
            op.execute(statement)


def _settle(dialect: str) -> None:
    """Rows written while the batches ran take their thread's tenant, or the one its events name; the rest move to the
    side tables; then the column refuses a row with no tenant."""
    before, after = backfill_ddl(_read(), dialect, chain=CHAIN)
    for statement in before:
        op.execute(statement)
    for name, key in TABLES.items():
        side, cols = SIDE[name], _kept(name)
        own = f"(SELECT g.tenant_id FROM graph_threads g WHERE g.id = {name}.thread_id)"
        op.execute(
            f"UPDATE {name} SET tenant_id = COALESCE({own}, {_events_tenant(f'{name}.thread_id')}) "
            "WHERE tenant_id IS NULL"
        )
        op.execute(
            f"INSERT INTO {side} ({cols}) SELECT {cols} FROM {name} x WHERE x.tenant_id IS NULL "
            f"AND NOT EXISTS (SELECT 1 FROM {side} s WHERE s.{key} = x.{key})"
        )
        there = f"EXISTS (SELECT 1 FROM {side} s WHERE s.{key} = {name}.{key})"
        op.execute(f"DELETE FROM {name} WHERE tenant_id IS NULL AND {there}")
    for statement in after:
        op.execute(statement)
    for name in TABLES:
        with op.batch_alter_table(name) as b:
            b.alter_column("tenant_id", existing_type=sa.String(64), nullable=False)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for name in TABLES:
            for statement in isolation_drop_ddl(_marked(name), dialect):
                op.execute(statement)
            if dialect == "postgresql":
                op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {name} FROM {TENANT_ROLE}")
    for name, key in TABLES.items():
        if dialect == "mssql":
            _drop_default(name, "tenant_id")
        op.drop_column(name, "tenant_id")
        # The side table's rows go back before it is dropped; they are the few no tenant was named for.
        side, cols = SIDE[name], _kept(name)
        op.execute(
            f"INSERT INTO {name} ({cols}) SELECT {cols} FROM {side} s "
            f"WHERE NOT EXISTS (SELECT 1 FROM {name} r WHERE r.{key} = s.{key})"
        )
        op.drop_table(side)


def _drop_default(name: str, column: str) -> None:
    """A database upgraded before the column lost its default still holds one, which SQL Server refuses to drop the
    column under; a database without one has nothing to drop, so the constraint is looked up first."""
    op.execute(mssql_drop_default_ddl(name, column))
