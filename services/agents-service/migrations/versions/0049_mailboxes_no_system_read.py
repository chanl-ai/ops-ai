"""mailboxes: revoke the system role's read (c-199)

Revision ID: 0049_mailboxes_no_system_read
Revises: 0048_agent_memories

0047 let ops_runtime_system (BYPASSRLS) read mailboxes for the listener. The listener reads a mailbox in its workflow's
tenant scope instead (74493d5f), and test_tenancy keeps the bypass role to the sweeper and timer loops, so the grant
only widens what that role can see.
"""

from __future__ import annotations

from alembic import op

revision = "0049_mailboxes_no_system_read"
down_revision = "0048_agent_memories"
branch_labels = None
depends_on = None

SYSTEM_ROLE = "ops_runtime_system"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE SELECT ON mailboxes FROM {SYSTEM_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT ON mailboxes TO {SYSTEM_ROLE}")
