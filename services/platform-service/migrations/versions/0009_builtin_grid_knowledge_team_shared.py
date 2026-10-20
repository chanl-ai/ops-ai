"""built-in grid: a builder changes and deletes any of the team's knowledge, not only their own

Knowledge is shared by its team (owner decision 2026-10-17, kb-service 147c7b4c): any builder or admin of the team
changes or deletes its knowledge bases and sources. 0006 gave Builder `knowledge.edit` and `knowledge.delete` on its
own records only; this widens both to `all` in every tenant and raises each tenant's permission version. Portable SQL
only; the built-in ids are reserved, so no custom role is matched.

Revision ID: 0009_knowledge_team_shared
Revises: 0008_chat_owner
"""

from __future__ import annotations

from alembic import op

revision = "0009_knowledge_team_shared"
down_revision = "0008_chat_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE role_permissions SET scope = 'all' "
        "WHERE role_id = 'builder' AND area = 'knowledge' AND action IN ('edit', 'delete')"
    )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    op.execute(
        "UPDATE role_permissions SET scope = 'own' "
        "WHERE role_id = 'builder' AND area = 'knowledge' AND action IN ('edit', 'delete')"
    )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
