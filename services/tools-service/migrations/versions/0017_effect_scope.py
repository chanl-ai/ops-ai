"""a write acts once by a portable unique index on effect_scope (c-070 review)

Revision ID: tools_0017_effect_scope
Revises: tools_0016_threadless_once

ux_gateway_calls_effect (0001) and its threadless twin (0016) were partial indexes (WHERE effect), which only
PostgreSQL honours: on MySQL or Azure SQL they become plain unique indexes on every row, so threaded calls collide.
Each row now carries effect_scope, never null: "thread:<id>" or "none" on the row holding a write's side effect, and
"row:<call id>" on every other row, which is unique by itself. One plain unique index on (tenant_id, effect_scope, step,
tool, input_hash) then lets exactly one row per approved write act, on every database.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0017_effect_scope"
down_revision = "tools_0016_threadless_once"
branch_labels = None
depends_on = None

calls = sa.table(
    "gateway_calls",
    sa.column("id", sa.String),
    sa.column("thread_id", sa.String),
    sa.column("effect", sa.Boolean),
    sa.column("effect_scope", sa.String),
)


def upgrade() -> None:
    op.add_column("gateway_calls", sa.Column("effect_scope", sa.String(80), nullable=True))
    scope = sa.case(
        (calls.c.effect & calls.c.thread_id.is_not(None), sa.func.concat("thread:", calls.c.thread_id)),
        (calls.c.effect, sa.literal("none")),
        else_=sa.func.concat("row:", calls.c.id),
    )
    op.execute(calls.update().values(effect_scope=scope))
    op.alter_column("gateway_calls", "effect_scope", existing_type=sa.String(80), nullable=False)
    op.drop_index("ux_gateway_calls_effect_threadless", table_name="gateway_calls")
    op.drop_index("ux_gateway_calls_effect", table_name="gateway_calls")
    op.create_index(
        "ux_gateway_calls_effect_scope",
        "gateway_calls",
        ["tenant_id", "effect_scope", "step", "tool", "input_hash"],
        unique=True,
    )


def downgrade() -> None:
    # Kept so the chain's revert-and-reapply test (tests/test_registry_store.py) still runs end to end.
    op.drop_index("ux_gateway_calls_effect_scope", table_name="gateway_calls")
    op.create_index(
        "ux_gateway_calls_effect",
        "gateway_calls",
        ["thread_id", "step", "tool", "input_hash"],
        unique=True,
        postgresql_where=sa.text("effect"),
    )
    op.create_index(
        "ux_gateway_calls_effect_threadless",
        "gateway_calls",
        ["tenant_id", "step", "tool", "input_hash"],
        unique=True,
        postgresql_where=sa.text("effect AND thread_id IS NULL"),
    )
    op.drop_column("gateway_calls", "effect_scope")
