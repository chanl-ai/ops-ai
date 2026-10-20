"""built-in grid: an admin's chat read is all scope, capped by the chatThreadsOwnerOnly policy

Admins hold every cell (0016) but chat reads stayed one's own in the grid. The read is now all scope for admins and
`can()` caps it at one's own while the workspace keeps chats private (`chatThreadsOwnerOnly`, on by default, c-186),
so nothing changes until an admin turns the policy off. Raises each tenant's permission version.

Revision ID: 0018_admin_chat_all
Revises: 0017_signin_domain_verification
"""

from __future__ import annotations

from alembic import op

revision = "0018_admin_chat_all"
down_revision = "0017_signin_domain_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE role_permissions SET scope = 'all' WHERE role_id = 'admin' AND area = 'chat' AND action = 'view'"
    )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    op.execute(
        "UPDATE role_permissions SET scope = 'own' WHERE role_id = 'admin' AND area = 'chat' AND action = 'view'"
    )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
