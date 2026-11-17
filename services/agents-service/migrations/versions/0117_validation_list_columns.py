"""Each workflow test run carries the counts the Evals lists read of it

Revision ID: 0117_validation_list_columns
Revises: 0116_tool_catalog_copies

The Evals suites, runs and publish checks (`GET /v1/assurance/*`) read a workflow test run's passed, total, regression
and failing-check counts out of its `summary` JSON, so the lists were built and paged in memory. registry_validations
gains `passed`, `total`, `regressions` and `checks_failing`, written in the same insert as the summary
(`store/workflow_registry.py` `summary_columns`), so the lists filter, count and page in SQL.

The fill reads BATCH rows at a time in key order, each batch one UPDATE of the rows it read, inside the migration's
transaction with the table's own policy set aside (on SQL Server it is dropped and made again before that transaction
ends). Only rows still without values are read, so a stopped run starts again where it left off. The columns are added
without a default and made NOT NULL once filled, so no default is left for a store that forgot them to fall back on.
Stop agents-service before upgrading (docs/deploy/database.md).

The down path drops the four columns, first any default constraint SQL Server holds on one, found by its table and
column. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any, cast

import sqlalchemy as sa
from alembic import op

from ops_store.schema import TENANT_SCOPED, backfill_ddl

revision = "0117_validation_list_columns"
down_revision = "0116_tool_catalog_copies"
branch_labels = None
depends_on = None

CHAIN = "agents"
TABLE = "registry_validations"
# Rows per UPDATE; under 5000, where SQL Server escalates row locks to a table lock.
BATCH = 1000
# Each column and the summary key it is read from, as of this revision.
COLUMNS = {"passed": "passed", "total": "total", "regressions": "regressions", "checks_failing": "checksFailing"}


def _validations() -> sa.Table:
    """registry_validations as far as the fill and its policy need, as of this revision."""
    return sa.Table(
        TABLE,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("id", sa.String(64)),
        sa.Column("summary", sa.JSON),
        *(sa.Column(name, sa.Integer()) for name in COLUMNS),
        info=TENANT_SCOPED,
    )


def _has_columns() -> bool:
    """Whether a stopped run already added them; offline SQL starts from 0116, where they are absent."""
    if op.get_context().as_sql:
        return False
    return "checks_failing" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def _count(summary: Any, key: str) -> int:
    value = cast(dict[str, Any], summary).get(key) if isinstance(summary, dict) else None
    return int(value) if isinstance(value, int | float) else 0


def _fill(t: sa.Table) -> None:
    """Reads every run still without counts out of its summary, BATCH at a time in key order."""
    if op.get_context().as_sql:
        return
    bind = op.get_bind()
    update = t.update().where(t.c.id == sa.bindparam("k_id")).values({name: sa.bindparam(name) for name in COLUMNS})
    while True:
        # Each batch fills the rows it read, so the next one reads the rows after them.
        q = sa.select(t.c.id, t.c.summary).where(t.c.checks_failing.is_(None)).order_by(t.c.id).limit(BATCH)
        rows = bind.execute(q).all()
        if not rows:
            return
        bind.execute(
            update,
            [{"k_id": r.id} | {name: _count(r.summary, key) for name, key in COLUMNS.items()} for r in rows],
        )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    t = _validations()
    if not _has_columns():
        with op.batch_alter_table(TABLE) as b:
            for name in COLUMNS:
                b.add_column(sa.Column(name, sa.Integer()))
    # Every tenant's runs are filled, so the table's own policy is set aside, only ever inside a transaction.
    before, after = backfill_ddl([t], dialect, chain=CHAIN, kind="tenant")
    for statement in before:
        op.execute(statement)
    _fill(t)
    for statement in after:
        op.execute(statement)
    with op.batch_alter_table(TABLE) as b:
        for name in COLUMNS:
            b.alter_column(name, existing_type=sa.Integer(), nullable=False)


def _drop_default_ddl(column: str) -> str:
    """SQL Server: drops the default constraint on TABLE.`column`, if one is there, found by its table and column."""
    return (
        "DECLARE @c sysname = (SELECT d.name FROM sys.default_constraints d JOIN sys.columns c "
        "ON c.object_id = d.parent_object_id AND c.column_id = d.parent_column_id "
        f"WHERE d.parent_object_id = OBJECT_ID(N'{TABLE}') AND c.name = N'{column}');\n"
        f"IF @c IS NOT NULL EXEC (N'ALTER TABLE {TABLE} DROP CONSTRAINT ' + QUOTENAME(@c));"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "mssql":
        for name in COLUMNS:
            op.execute(_drop_default_ddl(name))
    with op.batch_alter_table(TABLE) as b:
        for name in COLUMNS:
            b.drop_column(name)
