"""Each v2 definition version carries what the Workflows list reads of it

Revision ID: 0115_workflow_list_columns
Revises: 0114_drop_local_tenant_defaults

`GET /v1/workflows` searched, filtered and paged in memory because a v2 workflow's description, trigger text, whether a
person starts it by hand and whether its start form takes a file were worked out in Python from the definition with
the node type registry. engine_definitions gains `description`, `trigger`, `startable` and `takes_files`, written with
each version (ops_engine `node_types.list_columns`, the same function the stores call), so the list is one statement.

The values need the registry, so each version is read and worked out here: BATCH rows at a time in key order, each
batch one UPDATE of the rows it read, inside the migration's transaction with the table's own policy set aside (on SQL
Server it is dropped and made again before that transaction ends). Only rows still without values are read, so a
stopped run starts again where it left off. The columns are added without a default and made NOT NULL once filled, so
no default is left for a store that forgot them to fall back on. Stop agents-service before upgrading
(docs/deploy/database.md).

The down path drops the four columns, first any default constraint SQL Server holds on one, found by its table and
column. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

from ops_engine import default_registry
from ops_engine.node_types import list_columns
from ops_store.schema import TENANT_SCOPED, backfill_ddl

revision = "0115_workflow_list_columns"
down_revision = "0114_drop_local_tenant_defaults"
branch_labels = None
depends_on = None

CHAIN = "agents"
TABLE = "engine_definitions"
# Rows per UPDATE; under 5000, where SQL Server escalates row locks to a table lock.
BATCH = 1000
COLUMNS: dict[str, sa.types.TypeEngine[Any]] = {
    "description": sa.Text(),
    "trigger": sa.Text(),
    "startable": sa.Boolean(),
    "takes_files": sa.Boolean(),
}


def _definitions() -> sa.Table:
    """engine_definitions as far as the fill and its policy need, as of this revision."""
    return sa.Table(
        TABLE,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("workflow_id", sa.String(64)),
        sa.Column("version", sa.Integer),
        sa.Column("definition", sa.JSON),
        *(sa.Column(name, kind) for name, kind in COLUMNS.items()),
        info=TENANT_SCOPED,
    )


def _has_columns() -> bool:
    """Whether a stopped run already added them; offline SQL starts from 0114, where they are absent."""
    if op.get_context().as_sql:
        return False
    return "startable" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def _fill(t: sa.Table) -> None:
    """Works out every version still without values, BATCH at a time in key order."""
    if op.get_context().as_sql:
        return
    registry = default_registry()
    bind = op.get_bind()
    key = (t.c.tenant_id, t.c.workflow_id, t.c.version)
    keyed = sa.and_(
        t.c.tenant_id == sa.bindparam("k_tenant"),
        t.c.workflow_id == sa.bindparam("k_workflow"),
        t.c.version == sa.bindparam("k_version"),
    )
    update = t.update().where(keyed).values({name: sa.bindparam(name) for name in COLUMNS})
    while True:
        # Each batch fills the rows it read, so the next one reads the rows after them.
        q = sa.select(*key, t.c.definition).where(t.c.startable.is_(None)).order_by(*key).limit(BATCH)
        rows = bind.execute(q).all()
        if not rows:
            return
        values = [
            {"k_tenant": r.tenant_id, "k_workflow": r.workflow_id, "k_version": r.version}
            | list_columns(r.definition or {}, registry)
            for r in rows
        ]
        bind.execute(update, values)


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    t = _definitions()
    if not _has_columns():
        with op.batch_alter_table(TABLE) as b:
            for name, kind in COLUMNS.items():
                b.add_column(sa.Column(name, kind))
    # Every tenant's versions are filled, so the table's own policy is set aside, only ever inside a transaction.
    before, after = backfill_ddl([t], dialect, chain=CHAIN, kind="tenant")
    for statement in before:
        op.execute(statement)
    _fill(t)
    for statement in after:
        op.execute(statement)
    with op.batch_alter_table(TABLE) as b:
        for name, kind in COLUMNS.items():
            b.alter_column(name, existing_type=kind, nullable=False)


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
