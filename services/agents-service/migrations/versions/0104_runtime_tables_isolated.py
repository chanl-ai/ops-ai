"""A thread's budget and its model-call ledger are held to the thread's tenant by the database

Revision ID: 0104_runtime_tables_isolated
Revises: 0103_eval_cases_runs

thread_budgets and model_call_records had no tenant column, so any statement that named a thread id read or wrote that
thread's budget and its recorded model responses whatever tenant asked. Each now carries the tenant of its thread and
the generated tenant policy, with no column default: the stores write the caller's tenant. Neither has a team column: a
budget and a call are reached only through their thread, whose own policy holds the team.

The column is added and each thread's tenant copied into a session table in one short transaction; the rows are then
filled in batches of BATCH, each committed alone, so no lock on the table lasts the whole fill. A last transaction fills
rows written meanwhile from graph_threads and deletes the rows whose thread is gone: every read of either table names
a thread, so nothing reads them, and a call's cost is also in the models service's call log. Left with a tenant of
`local`, a tenant of that name would read them. Runs on PostgreSQL and SQL Server, and again after a stopped run.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import (
    TEAM_OWNED,
    TENANT_SCOPED,
    backfill_ddl,
    isolation_ddl,
    isolation_drop_ddl,
    mssql_predicates_ddl,
    session_table_ddl,
)

revision = "0104_runtime_tables_isolated"
down_revision = "0103_eval_cases_runs"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
# Each table and its key.
TABLES = {"thread_budgets": "thread_id", "model_call_records": "id"}
# Rows per committed batch; under 5000, where SQL Server escalates row locks to a table lock.
BATCH = 4000


def _marked(name: str) -> sa.Table:
    """The table as far as its isolation needs, as of this revision."""
    return sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _threads() -> sa.Table:
    return sa.Table(
        "graph_threads",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _has_tenant(name: str) -> bool:
    """Whether a stopped run already added the column; offline SQL starts from 0103, where none has it."""
    if op.get_context().as_sql:
        return False
    return "tenant_id" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(name)}


def _copy(dialect: str) -> tuple[str, list[str]]:
    """The session table holding each thread's tenant, and the statements that fill it."""
    copy = "#thread_tenants_0104" if dialect == "mssql" else "thread_tenants_0104"
    return copy, [
        session_table_ddl(copy, dialect, [("id", 64), ("tenant_id", 64)]),
        f"INSERT INTO {copy} (id, tenant_id) SELECT id, tenant_id FROM graph_threads",
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


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    for name in TABLES:
        if not _has_tenant(name):
            op.add_column(name, sa.Column("tenant_id", sa.String(64), nullable=True))
    if dialect not in ("postgresql", "mssql"):
        _settle(dialect)
        return
    # graph_threads' own policy is set aside only inside a transaction, never across a commit.
    copy, statements = _copy(dialect)
    before, after = backfill_ddl([_threads()], dialect, chain=CHAIN)
    for statement in [*before, *statements, *after]:
        op.execute(statement)
    with op.get_context().autocommit_block():
        for name, key in TABLES.items():
            op.execute(_fill(dialect, copy, name, key))
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
    """Rows written while the batches ran take their thread's tenant; rows whose thread is gone are deleted; then the
    column refuses a row with no tenant."""
    before, after = backfill_ddl([_threads()], dialect, chain=CHAIN)
    for statement in before:
        op.execute(statement)
    for name in TABLES:
        op.execute(
            f"UPDATE {name} SET tenant_id = (SELECT g.tenant_id FROM graph_threads g WHERE g.id = {name}.thread_id) "
            f"WHERE tenant_id IS NULL AND EXISTS (SELECT 1 FROM graph_threads g WHERE g.id = {name}.thread_id)"
        )
        op.execute(f"DELETE FROM {name} WHERE tenant_id IS NULL")
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
    for name in TABLES:
        if dialect == "mssql":
            _drop_default(name, "tenant_id")
        op.drop_column(name, "tenant_id")


def _drop_default(name: str, column: str) -> None:
    """A database upgraded before the column lost its default still holds one, which SQL Server refuses to drop the
    column under; a database without one has nothing to drop, so the constraint is looked up first."""
    op.execute(
        f"DECLARE @n sysname = (SELECT d.name FROM sys.default_constraints d WHERE d.parent_object_id = "
        f"OBJECT_ID(N'{name}') AND COL_NAME(d.parent_object_id, d.parent_column_id) = N'{column}'); "
        # EXEC takes a variable or literals, not a function call, so the statement is built first.
        f"IF @n IS NOT NULL BEGIN DECLARE @s nvarchar(max) = N'ALTER TABLE {name} DROP CONSTRAINT ' "
        f"+ QUOTENAME(@n); EXEC (@s); END"
    )
