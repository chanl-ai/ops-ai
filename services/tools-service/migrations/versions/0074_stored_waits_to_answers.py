"""stored_waits_answers: a write stored as "every call waits" becomes the tool's own reviewer answer

The gateway no longer reads requires_approval (the tool's own answer is approval_mode), so a write that was set to wait
would run unasked. Each such write on which no answer is set takes approval_mode "reviewer", which waits as before and
which a team admin can change per tool. Rows that already hold an approval_mode, reads and unset or false rows are
not touched. Downgrade leaves the answers: requires_approval still holds the old value.

Revision ID: tools_0074_stored_waits_answers
Revises: tools_0073_tool_approval_mode
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0074_stored_waits_answers"
down_revision = "tools_0073_tool_approval_mode"
branch_labels = None
depends_on = None

operations = sa.table(
    "module_operations",
    sa.column("access", sa.String),
    sa.column("requires_approval", sa.Boolean),
    sa.column("approval_mode", sa.String),
)


def upgrade() -> None:
    op.execute(
        sa.update(operations)
        .where(
            operations.c.access == "write",
            operations.c.requires_approval == sa.true(),
            operations.c.approval_mode.is_(None),
        )
        .values(approval_mode="reviewer")
    )


def downgrade() -> None:
    return
