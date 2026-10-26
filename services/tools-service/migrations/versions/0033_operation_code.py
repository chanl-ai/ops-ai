"""module_operations.code: a code operation's function, the tools and secrets it may use, and its limits (c-531)

An operation with executor `code` runs a builder's Python function on runner-service. Its source, entry, bound tool
names, secret names and limits are one JSON value, null for every other executor.

Revision ID: tools_0033_operation_code
Revises: tools_0032_platform_no_team
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0033_operation_code"
down_revision = "tools_0032_platform_no_team"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_operations", sa.Column("code", sa.JSON))


def downgrade() -> None:
    op.drop_column("module_operations", "code")
