"""built-in grid: chat threads are read by their owner only, and three team-admin rules

0006 gave every built-in role `chat.view` on every thread, but agents-service shows a chat thread only to the person
who started it, admins included (`chat_threads.owned_by`), so the built-in roles read only their own (`own`). It also
left out three rules agents-service gives a team admin: raising a spent chat's budget (`chat.manage`), raising a run
thread's budget (`cases.decide`, `chat_budget.run_api_answer`) and setting which publishes need a review
(`reviews.manage`, `publish_policy.require_admin`). Brings every tenant's rows to `ops_platform/permissions.py` and
raises each tenant's permission version. Portable SQL only; built-in ids are reserved, so no custom role is matched.

Revision ID: 0008_chat_owner
Revises: 0007_grid_fixes
"""

from __future__ import annotations

from alembic import op

revision = "0008_chat_owner"
down_revision = "0007_grid_fixes"
branch_labels = None
depends_on = None

MEMBER_ROLES = "('admin', 'builder', 'reviewer', 'viewer')"
ADMIN_RULES = (("chat", "manage"), ("cases", "decide"), ("reviews", "manage"))


def upgrade() -> None:
    op.execute(
        f"UPDATE role_permissions SET scope = 'own' "
        f"WHERE role_id IN {MEMBER_ROLES} AND area = 'chat' AND action = 'view'"
    )
    for area, action in ADMIN_RULES:
        op.execute(
            "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
            f"SELECT tenant_id, id, '{area}', '{action}', 'all' FROM roles WHERE id = 'admin'"
        )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    for area, action in ADMIN_RULES:
        op.execute(f"DELETE FROM role_permissions WHERE role_id = 'admin' AND area = '{area}' AND action = '{action}'")
    op.execute(
        f"UPDATE role_permissions SET scope = 'all' "
        f"WHERE role_id IN {MEMBER_ROLES} AND area = 'chat' AND action = 'view'"
    )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
