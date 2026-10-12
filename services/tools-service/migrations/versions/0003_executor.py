"""operation executor, headers and body; call log latency, error and token fingerprint

What the executor behind /v1/calls needs: how each operation runs, and what /v1/executions reports per call.

Revision ID: tools_0003_executor
Revises: tools_0002_registry
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0003_executor"
down_revision = "tools_0002_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gateway_calls", sa.Column("module_id", sa.String(length=64), nullable=True))
    op.add_column("gateway_calls", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column("gateway_calls", sa.Column("error", sa.JSON(), nullable=True))
    op.add_column("gateway_calls", sa.Column("approval_token_id", sa.String(length=64), nullable=True))
    op.add_column(
        "module_operations", sa.Column("executor", sa.String(length=8), server_default="http", nullable=False)
    )
    op.add_column("module_operations", sa.Column("headers", sa.JSON(), server_default="[]", nullable=False))
    op.add_column("module_operations", sa.Column("body", sa.Text(), nullable=True))

    # Revision 0 now marks a module as the dev seed wrote it. A module still at revision 1 was inserted and never
    # edited (an edit raises it), and the seed only ever rewrites its own ids, so marking these lets it refresh them.
    op.execute("UPDATE tool_modules SET revision = 0 WHERE revision = 1")


def downgrade() -> None:
    op.drop_column("module_operations", "body")
    op.drop_column("module_operations", "headers")
    op.drop_column("module_operations", "executor")
    op.drop_column("gateway_calls", "approval_token_id")
    op.drop_column("gateway_calls", "error")
    op.drop_column("gateway_calls", "latency_ms")
    op.drop_column("gateway_calls", "module_id")
