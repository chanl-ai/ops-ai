"""gateway calls and fences, adopted from agents-service's chain

Revision ID: tools_0001_gateway
Revises:

agents-service's migrations 0006 and 0008 created these tables before tools-service had its own chain, and existing
databases have them. This revision creates each table and its indexes only when missing, so it is a no-op on a
database the agents chain already migrated and the full schema on a fresh one. The agents chain stops creating them
in a later revision, once nothing in agents-service reads them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0001_gateway"
down_revision = None
branch_labels = None
depends_on = None


def _missing(table: str) -> bool:
    return not sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _missing("gateway_calls"):
        op.create_table(
            "gateway_calls",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tool", sa.String(length=64), nullable=False),
            sa.Column("access", sa.String(length=32), nullable=False),
            sa.Column("input_hash", sa.String(length=64), nullable=False),
            sa.Column("idempotency_key", sa.String(length=200), nullable=False),
            sa.Column("thread_id", sa.String(length=64), nullable=True),
            sa.Column("step", sa.String(length=200), nullable=True),
            sa.Column("sub", sa.String(length=200), nullable=False),
            sa.Column("act", sa.String(length=200), nullable=True),
            sa.Column("decision", sa.String(length=8), nullable=False),
            sa.Column("reasons", sa.JSON(), nullable=False),
            sa.Column("approvers", sa.JSON(), nullable=False),
            sa.Column("outcome", sa.String(length=16), nullable=False),
            sa.Column("effect", sa.Boolean(), nullable=False),
            sa.Column("output", sa.JSON(), nullable=True),
            sa.Column("view", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_gateway_calls_thread_id", "gateway_calls", ["thread_id"])
        # At most one call per approved write carries the side effect; a retry gets the first call's result.
        op.create_index(
            "ux_gateway_calls_effect",
            "gateway_calls",
            ["thread_id", "step", "tool", "input_hash"],
            unique=True,
            postgresql_where=sa.text("effect"),
        )
    if _missing("gateway_fences"):
        op.create_table(
            "gateway_fences",
            sa.Column("thread_id", sa.String(length=64), nullable=False),
            sa.Column("generation", sa.BigInteger(), nullable=False),
            sa.PrimaryKeyConstraint("thread_id"),
        )


def downgrade() -> None:
    # Adopted tables may still belong to the agents chain on this database; leave them to whichever chain created them.
    pass
