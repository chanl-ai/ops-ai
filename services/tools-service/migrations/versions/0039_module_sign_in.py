"""Whose account a module and an operation sign in with (c-558)

`tool_modules.sign_in` is the sign-in a module supports: `team`, `person` or `either` (every module before this one);
choosing a connection whose sign-in does not fit is refused. `module_operations.needs_person` marks an operation only
a person's own sign-in may sign: a call with nobody behind it is refused even where the team backup is on.

Revision ID: tools_0039_module_sign_in
Revises: tools_0038_connection_health
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0039_module_sign_in"
down_revision = "tools_0038_connection_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_modules", sa.Column("sign_in", sa.String(16), nullable=False, server_default="either"))
    op.add_column("module_operations", sa.Column("needs_person", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("module_operations", "needs_person")
    op.drop_column("tool_modules", "sign_in")
