"""built-in grid: a team admin holds every cell

The owner decided admins do everything (2026-10-17): the admin role holds every area and action of the catalogue in
its team, all scope, except reading chat threads and editing memory, which stay one's own until the
chatThreadsOwnerOnly policy decides chat (c-186). Actions held in the Security team still need a role there. Adds
each missing cell to every tenant's admin role and raises each tenant's permission version. The catalogue is frozen
here as it stood: a later cell needs its own migration. Portable SQL only; built-in ids are reserved.

Revision ID: 0016_admin_every_cell
Revises: 0015_memory_edit
"""

from __future__ import annotations

from alembic import op

revision = "0016_admin_every_cell"
down_revision = "0015_memory_edit"
branch_labels = None
depends_on = None

AREAS = (
    "agents",
    "workflows",
    "skills",
    "guardrails",
    "widgets",
    "knowledge",
    "tools",
    "secrets_egress",
    "files",
    "chat",
    "memory",
    "reviews",
    "cases",
    "deployments",
    "settings",
    "access",
    "audit",
)
ACTIONS = ("view", "create", "edit", "publish", "delete", "run", "decide", "manage")
OWN = {("chat", "view"), ("memory", "edit")}
# What the admin role held before this revision, so the downgrade removes exactly what it added.
BEFORE = frozenset(
    {
        ("access", "create"),
        ("access", "delete"),
        ("access", "edit"),
        ("access", "manage"),
        ("access", "view"),
        ("agents", "create"),
        ("agents", "decide"),
        ("agents", "delete"),
        ("agents", "edit"),
        ("agents", "manage"),
        ("agents", "publish"),
        ("agents", "run"),
        ("agents", "view"),
        ("audit", "view"),
        ("cases", "decide"),
        ("cases", "manage"),
        ("cases", "view"),
        ("chat", "decide"),
        ("chat", "manage"),
        ("chat", "run"),
        ("chat", "view"),
        ("deployments", "create"),
        ("deployments", "edit"),
        ("deployments", "run"),
        ("deployments", "view"),
        ("files", "create"),
        ("files", "delete"),
        ("files", "manage"),
        ("files", "view"),
        ("guardrails", "create"),
        ("guardrails", "decide"),
        ("guardrails", "delete"),
        ("guardrails", "edit"),
        ("guardrails", "publish"),
        ("guardrails", "view"),
        ("knowledge", "create"),
        ("knowledge", "delete"),
        ("knowledge", "edit"),
        ("knowledge", "manage"),
        ("knowledge", "view"),
        ("memory", "edit"),
        ("reviews", "decide"),
        ("reviews", "manage"),
        ("reviews", "view"),
        ("secrets_egress", "view"),
        ("skills", "create"),
        ("skills", "decide"),
        ("skills", "delete"),
        ("skills", "edit"),
        ("skills", "publish"),
        ("skills", "view"),
        ("tools", "create"),
        ("tools", "decide"),
        ("tools", "delete"),
        ("tools", "edit"),
        ("tools", "manage"),
        ("tools", "publish"),
        ("tools", "run"),
        ("tools", "view"),
        ("widgets", "create"),
        ("widgets", "decide"),
        ("widgets", "edit"),
        ("widgets", "publish"),
        ("widgets", "view"),
        ("workflows", "create"),
        ("workflows", "decide"),
        ("workflows", "delete"),
        ("workflows", "edit"),
        ("workflows", "publish"),
        ("workflows", "run"),
        ("workflows", "view"),
    }
)


def upgrade() -> None:
    for area in AREAS:
        for action in ACTIONS:
            scope = "own" if (area, action) in OWN else "all"
            op.execute(
                "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                f"SELECT r.tenant_id, r.id, '{area}', '{action}', '{scope}' FROM roles r WHERE r.id = 'admin' "
                "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
                f"AND p.role_id = r.id AND p.area = '{area}' AND p.action = '{action}')"
            )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    for area in AREAS:
        for action in ACTIONS:
            if (area, action) not in BEFORE:
                op.execute(
                    f"DELETE FROM role_permissions WHERE role_id = 'admin' AND area = '{area}' AND action = '{action}'"
                )
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
