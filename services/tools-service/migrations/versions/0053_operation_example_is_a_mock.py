"""module_operations.stub moves into operation_mocks: an operation's example answer is its "example" mock

The stub and the mock answers were two homes for what Mock answers. Each operation's stub becomes one mock in the
"example" environment, which test-environment calls never read, with the operation's id as its id (unique in the
tenant, and apart from the mck_ ids mocks are made with). Then the column goes. Plain SQL both ways, so the upgrade
bundle renders it offline.

Revision ID: tools_0053_operation_example
Revises: tools_0052_reconnect_notice
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "tools_0053_operation_example"
down_revision = "tools_0052_reconnect_notice"
branch_labels = None
depends_on = None

EXAMPLE = "example"

ops = sa.table(
    "module_operations",
    sa.column("tenant_id", sa.String),
    sa.column("id", sa.String),
    sa.column("module_id", sa.String),
    sa.column("name", sa.String),
    sa.column("stub", sa.JSON),
)
mocks = sa.table(
    "operation_mocks",
    sa.column("tenant_id", sa.String),
    sa.column("id", sa.String),
    sa.column("module_id", sa.String),
    sa.column("operation", sa.String),
    sa.column("environment", sa.String),
    sa.column("position", sa.Integer),
    sa.column("name", sa.String),
    sa.column("match", sa.JSON),
    sa.column("status", sa.Integer),
    sa.column("body", sa.JSON),
    sa.column("headers", sa.JSON),
    sa.column("delay_ms", sa.Integer),
    sa.column("timeout", sa.Boolean),
    sa.column("is_default", sa.Boolean),
    sa.column("from_call_id", sa.String),
    sa.column("created_by", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def _empty() -> sa.Cast[Any]:
    return sa.cast(sa.literal("{}"), sa.JSON)


def upgrade() -> None:
    now = sa.func.current_timestamp()
    columns = [
        "tenant_id", "id", "module_id", "operation", "environment", "position", "name", "match", "status", "body",
        "headers", "delay_ms", "timeout", "is_default", "from_call_id", "created_by", "created_at", "updated_at",
    ]  # fmt: skip
    rows = sa.select(
        ops.c.tenant_id, ops.c.id, ops.c.module_id, ops.c.name, sa.literal(EXAMPLE), sa.literal(1),
        sa.literal("Example answer"), _empty(), sa.literal(200), ops.c.stub, _empty(), sa.literal(0), sa.false(),
        sa.true(), sa.null(), sa.literal("operation example"), now, now,
    )  # fmt: skip
    op.execute(mocks.insert().from_select(columns, rows))
    with op.batch_alter_table("module_operations") as b:
        b.drop_column("stub")


def downgrade() -> None:
    with op.batch_alter_table("module_operations") as b:
        b.add_column(sa.Column("stub", sa.JSON))
    example = (
        sa.select(mocks.c.body)
        .where(
            mocks.c.tenant_id == ops.c.tenant_id,
            mocks.c.module_id == ops.c.module_id,
            mocks.c.operation == ops.c.name,
            mocks.c.environment == EXAMPLE,
            mocks.c.is_default == sa.true(),
        )
        .limit(1)
        .scalar_subquery()
    )
    # A correlated subquery rather than UPDATE ... FROM, which PostgreSQL and SQL Server write differently.
    op.execute(ops.update().values(stub=example))
    op.execute(ops.update().where(ops.c.stub.is_(None)).values(stub=sa.cast(sa.literal('{"ok": true}'), sa.JSON)))
    with op.batch_alter_table("module_operations") as b:
        b.alter_column("stub", existing_type=sa.JSON, nullable=False)
    op.execute(mocks.delete().where(mocks.c.environment == EXAMPLE))
